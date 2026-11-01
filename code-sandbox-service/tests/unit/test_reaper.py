from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.sandbox.reaper import expiry_reason

CFG = Settings(SANDBOX_IDLE_TTL_SECONDS=1200, SANDBOX_MAX_LIFETIME_SECONDS=14400)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def ago(**kw):
    return NOW - timedelta(**kw)


def test_active_session_is_kept():
    assert expiry_reason(ago(minutes=30), ago(minutes=5), NOW, CFG) is None


def test_idle_session_is_reaped():
    assert expiry_reason(ago(minutes=60), ago(minutes=21), NOW, CFG) == "idle"


def test_old_session_is_reaped_even_if_recently_used():
    assert expiry_reason(ago(hours=5), ago(seconds=10), NOW, CFG) == "max_lifetime"
