"""
Symmetric encryption for OAuth tokens at rest (Fernet — AES128-CBC + HMAC,
authenticated encryption). The key comes from TOKEN_ENCRYPTION_KEY in settings,
which MUST be a URL-safe base64-encoded 32-byte key (generate with
`Fernet.generate_key()`). Rotating this key invalidates every stored token —
document this clearly in CREDENTIALS.md when this ships.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import settings


@lru_cache
def _fernet() -> Fernet:
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set — required for storing OAuth tokens. "
            "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
