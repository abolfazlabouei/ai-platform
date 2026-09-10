"""Shared HTTP helpers for calling the ai-platform API services."""
import json
from typing import Any, Iterator, Optional

import requests


class ApiError(Exception):
    """Raised with a human-readable message extracted from a FastAPI error response."""


def _auth_headers(token: str) -> dict:
    if not token:
        raise ApiError("No auth token set — generate or paste one in the Auth tab first.")
    return {"Authorization": f"Bearer {token}"}


def _raise_for_status(resp: requests.Response) -> None:
    if resp.ok:
        return
    detail = resp.text
    try:
        detail = resp.json().get("detail", detail)
    except ValueError:
        pass
    raise ApiError(f"HTTP {resp.status_code}: {detail}")


def request_json(
    method: str,
    url: str,
    token: str,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    resp = requests.request(
        method,
        url,
        headers=_auth_headers(token),
        json=json_body,
        params=params,
        timeout=60,
    )
    _raise_for_status(resp)
    if not resp.content:
        return None
    return resp.json()


def upload_file(url: str, token: str, filename: str, file_bytes: bytes) -> Any:
    resp = requests.post(
        url,
        headers=_auth_headers(token),
        files={"file": (filename, file_bytes)},
        timeout=120,
    )
    _raise_for_status(resp)
    return resp.json()


def stream_sse(url: str, token: str, json_body: dict) -> Iterator[tuple[str, dict]]:
    """POST to an SSE endpoint and yield (event_type, data_dict) frames as they arrive."""
    headers = {**_auth_headers(token), "Content-Type": "application/json"}
    with requests.post(url, headers=headers, json=json_body, stream=True, timeout=300) as resp:
        _raise_for_status(resp)
        event_type = None
        data_lines: list[str] = []
        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            line = raw_line.strip("\r")
            if line == "":
                if event_type is not None:
                    data_raw = "\n".join(data_lines)
                    try:
                        data = json.loads(data_raw) if data_raw else {}
                    except json.JSONDecodeError:
                        data = {"raw": data_raw}
                    yield event_type, data
                event_type, data_lines = None, []
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
