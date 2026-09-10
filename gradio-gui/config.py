"""Base URLs for the three backend services, overridable via env vars.

Defaults target the docker-compose host-port mapping (see docker-compose.yml)
for standalone local dev; the compose service itself overrides these to the
internal container hostnames.
"""
import os

from dotenv import load_dotenv

load_dotenv()

CHAT_BASE_URL = os.environ.get("CHAT_BASE_URL", "http://localhost:8101/api/v1")
FILES_BASE_URL = os.environ.get("FILES_BASE_URL", "http://localhost:8102/api/v1")
KB_BASE_URL = os.environ.get("KB_BASE_URL", "http://localhost:8103/api/v1")
