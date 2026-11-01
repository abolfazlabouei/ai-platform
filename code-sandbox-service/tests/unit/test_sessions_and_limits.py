"""Session caps, dead-container replacement, the per-session lock and abuse limits (DB/Docker faked)."""
import asyncio
import uuid
from types import SimpleNamespace

import fakeredis
import pytest

from app.core.config import Settings
from app.models.sandbox_session import SessionStatus
from app.sandbox.executor import RunResult
from app.services.execution_service import ExecutionService, RateLimited, SessionBusy
from app.services.session_service import CapacityError, SessionNotFound, SessionService

CFG = Settings(SANDBOX_MAX_SESSIONS=3, SANDBOX_MAX_SESSIONS_PER_USER=2, SANDBOX_LOCK_WAIT_SECONDS=1,
               SANDBOX_RATE_LIMIT_PER_MINUTE=3, SANDBOX_DAILY_CPU_SECONDS_PER_USER=10)


class FakeRepo:
    def __init__(self):
        self.rows: list[SimpleNamespace] = []

    async def get(self, sid):
        return next((r for r in self.rows if r.id == sid), None)

    async def get_active_for_conversation(self, cid):
        return next((r for r in self.rows if r.conversation_id == cid and r.status != SessionStatus.TERMINATED), None)

    async def count_active(self, user_id=None):
        return sum(1 for r in self.rows if r.status != SessionStatus.TERMINATED
                   and (user_id is None or r.user_id == user_id))

    async def create(self, **fields):
        row = SimpleNamespace(id=uuid.uuid4(), container_id=None, **fields)
        self.rows.append(row)
        return row

    async def touch(self, row):
        pass

    async def mark_terminated(self, row, reason):
        row.status, row.container_id = SessionStatus.TERMINATED, None

    async def commit(self):
        pass


class FakePool:
    def __init__(self):
        self.created = 0

    async def claim(self, image):
        return None

    async def create_container(self, image, session_id):
        self.created += 1
        return f"container-{self.created}"

    def refill_in_background(self, image):
        pass


class FakeBackend:
    def __init__(self):
        self.running: set[str] = set()
        self.removed: list[str] = []

    def state(self, cid):
        return {"Running": True} if cid in self.running else None

    def remove(self, cid):
        self.removed.append(cid)
        self.running.discard(cid)


def make_service():
    backend, pool = FakeBackend(), FakePool()
    svc = SessionService(db=None, backend=backend, pool=pool, cfg=CFG)
    svc.repo = FakeRepo()
    return svc, backend, pool


async def test_get_or_create_is_per_conversation():
    svc, _, _ = make_service()
    a = await svc.get_or_create("conv-1", "u1")
    again = await svc.get_or_create("conv-1", "u1")
    assert a is again
    assert a.status == SessionStatus.READY and a.container_id == "container-1"


async def test_other_users_conversation_is_not_reachable():
    svc, _, _ = make_service()
    await svc.get_or_create("conv-1", "u1")
    with pytest.raises(SessionNotFound):
        await svc.get_or_create("conv-1", "attacker")


async def test_per_user_cap():
    svc, _, _ = make_service()
    await svc.get_or_create("c1", "u1")
    await svc.get_or_create("c2", "u1")
    with pytest.raises(CapacityError):
        await svc.get_or_create("c3", "u1")


async def test_global_cap_never_evicts_others():
    svc, _, _ = make_service()
    await svc.get_or_create("c1", "u1")
    await svc.get_or_create("c2", "u2")
    await svc.get_or_create("c3", "u3")
    with pytest.raises(CapacityError):
        await svc.get_or_create("c4", "u4")
    assert sum(r.status == SessionStatus.READY for r in svc.repo.rows) == 3


async def test_terminated_session_frees_a_slot():
    svc, _, _ = make_service()
    a = await svc.get_or_create("c1", "u1")
    await svc.get_or_create("c2", "u1")
    await svc.terminate(a, "test")
    await svc.get_or_create("c3", "u1")


async def test_dead_container_is_replaced_transparently():
    svc, backend, _ = make_service()
    row = await svc.get_or_create("c1", "u1")
    backend.running.add(row.container_id)
    handle = await svc.ensure_container(row)
    assert handle.workspace_reset is False

    backend.running.clear()  # OOM / crash
    handle = await svc.ensure_container(row)
    assert handle.workspace_reset is True
    assert handle.container_id == "container-2"
    assert "container-1" in backend.removed


# --- ExecutionService: lock + limits ---


class SlowExecutor:
    def __init__(self, delay=0.0):
        self.delay = delay

    async def run_python(self, cid, eid, code, timeout):
        await asyncio.sleep(self.delay)
        return RunResult(exit_code=0, stdout="", stderr="", stdout_bytes=0, stderr_bytes=0, truncated=False,
                         timed_out=False, oom_killed=False, duration_ms=4000, started_at=0.0)


class NoArtifacts:
    async def collect(self, *a):
        return []


class FakeExecRepo:
    async def create(self, **fields):
        return SimpleNamespace(**fields)


async def make_exec_service(delay=0.0):
    svc, backend, _ = make_service()
    row = await svc.get_or_create("c1", "u1")
    backend.running.add(row.container_id)
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    ex = ExecutionService(svc, SlowExecutor(delay), NoArtifacts(), r, CFG)
    ex.repo = FakeExecRepo()
    return ex, row


async def test_concurrent_exec_in_same_session_fails_cleanly():
    ex, row = await make_exec_service(delay=2.0)
    first = asyncio.create_task(ex.run(row, "print(1)", 5))
    await asyncio.sleep(0.1)
    with pytest.raises(SessionBusy):
        await ex.run(row, "print(2)", 5)
    assert (await first)["exit_code"] == 0


async def test_rate_limit_per_minute():
    ex, row = await make_exec_service()
    for _ in range(2):  # 2 x 4s stays under the 10s daily budget
        await ex.run(row, "print(1)", 5)
    await ex._check_limits(row.user_id)  # 3rd call this minute: allowed
    with pytest.raises(RateLimited):
        await ex._check_limits(row.user_id)  # 4th: over SANDBOX_RATE_LIMIT_PER_MINUTE


async def test_daily_cpu_budget():
    ex, row = await make_exec_service()
    await ex.run(row, "print(1)", 5)  # 4s
    await ex.run(row, "print(1)", 5)  # 8s
    await ex.redis.delete(*[k async for k in ex.redis.scan_iter("sandbox:rate:*")])
    await ex.run(row, "print(1)", 5)  # 12s >= 10s budget after this one
    await ex.redis.delete(*[k async for k in ex.redis.scan_iter("sandbox:rate:*")])
    with pytest.raises(RateLimited, match="budget"):
        await ex.run(row, "print(1)", 5)
