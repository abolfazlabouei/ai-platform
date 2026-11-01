"""Shared fixtures: the real SQLAlchemy models on in-memory SQLite + an in-memory skill store."""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.db.session import Base


class FakeStorage:
    """Stands in for MinIO: same interface as app.skills.storage.SkillStorage."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, data, mime):
        self.objects[key] = data

    async def get(self, key):
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key]

    async def delete_prefix(self, prefix):
        for key in [k for k in self.objects if k.startswith(prefix)]:
            del self.objects[key]

    async def presign(self, key):
        return f"http://files.test/{key}?sig=1"


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(session_maker):
    async with session_maker() as session:
        yield session
