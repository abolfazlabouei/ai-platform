"""Dev JWT generation — mirrors infra/scripts/generate_dev_token.py so the
Gradio app can mint tokens without depending on the rest of the repo."""
import time

import jwt

DEFAULT_SECRET = "dev-shared-jwt-secret-change-in-production"


def generate_dev_token(user_id: str, secret: str, expires_hours: int) -> str:
    user_id = user_id.strip() or "demo-user-1"
    secret = secret.strip() or DEFAULT_SECRET
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + int(expires_hours) * 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")
