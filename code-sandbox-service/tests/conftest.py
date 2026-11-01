"""Test-wide settings: deterministic secrets (>= 32 bytes, as production requires)."""
import os

os.environ.setdefault("SANDBOX_SHARED_SECRET", "test-shared-secret-0123456789abcdef0123")
os.environ.setdefault("SANDBOX_CONTEXT_SECRET", "test-context-secret-0123456789abcdef012")
