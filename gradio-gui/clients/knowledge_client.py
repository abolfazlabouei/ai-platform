"""knowledge-service client."""
from typing import Any

from config import KB_BASE_URL

from .base import request_json


def create_kb(token: str, name: str, description: str) -> dict:
    body = {"name": name}
    if description:
        body["description"] = description
    return request_json("POST", f"{KB_BASE_URL}/knowledge-bases", token, json_body=body)


def list_kbs(token: str) -> list:
    return request_json("GET", f"{KB_BASE_URL}/knowledge-bases", token)


def get_kb(token: str, kb_id: str) -> dict:
    return request_json("GET", f"{KB_BASE_URL}/knowledge-bases/{kb_id}", token)


def update_kb(token: str, kb_id: str, patch: dict) -> dict:
    return request_json("PATCH", f"{KB_BASE_URL}/knowledge-bases/{kb_id}", token, json_body=patch)


def delete_kb(token: str, kb_id: str) -> Any:
    return request_json("DELETE", f"{KB_BASE_URL}/knowledge-bases/{kb_id}", token)


def get_kb_sources(token: str, kb_id: str) -> list:
    return request_json("GET", f"{KB_BASE_URL}/knowledge-bases/{kb_id}/sources", token)


def ingest_files(token: str, kb_id: str, file_ids: list) -> dict:
    return request_json(
        "POST", f"{KB_BASE_URL}/knowledge-bases/{kb_id}/ingest", token, json_body={"file_ids": file_ids}
    )


def search(token: str, kb_ids: list, query: str, top_k: int) -> dict:
    return request_json(
        "POST", f"{KB_BASE_URL}/search", token, json_body={"kb_ids": kb_ids, "query": query, "top_k": top_k}
    )


def get_job_status(token: str, job_id: str) -> dict:
    # Ingest jobs are tracked the same way as file-processing jobs, but served
    # by knowledge-service's own /jobs endpoint per API.md.
    return request_json("GET", f"{KB_BASE_URL}/jobs/{job_id}/status", token)
