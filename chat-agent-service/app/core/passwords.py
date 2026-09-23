"""
Password hashing via bcrypt directly (not passlib — passlib has known
compatibility issues with recent bcrypt releases; the bcrypt package alone is
simpler and sufficient here).
"""
from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))