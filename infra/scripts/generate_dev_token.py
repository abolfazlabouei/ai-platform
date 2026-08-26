#!/usr/bin/env python3
"""
Generates a dev-only JWT for testing the API directly (Swagger UI, curl, Postman,
frontend local dev) without standing up a real auth/gateway service.

All three services validate tokens against the same JWT_SECRET (see
CREDENTIALS.md), so one token generated here works against chat-agent-service,
file-processing-service, and knowledge-service alike.

Usage:
    python3 generate_dev_token.py [user_id] [--secret SECRET] [--expires-hours N]

Example:
    python3 generate_dev_token.py demo-user-1
"""
from __future__ import annotations

import argparse
import time

import jwt

DEFAULT_SECRET = "dev-shared-jwt-secret-change-in-production"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", nargs="?", default="demo-user-1")
    parser.add_argument("--secret", default=DEFAULT_SECRET)
    parser.add_argument("--expires-hours", type=int, default=24)
    args = parser.parse_args()

    now = int(time.time())
    payload = {
        "sub": args.user_id,
        "iat": now,
        "exp": now + args.expires_hours * 3600,
    }
    token = jwt.encode(payload, args.secret, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
