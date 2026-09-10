"""file-processing-service client."""
from typing import Any

from config import FILES_BASE_URL

from .base import request_json, upload_file


def upload_document(token: str, filename: str, file_bytes: bytes) -> dict:
    return upload_file(f"{FILES_BASE_URL}/files", token, filename, file_bytes)


def list_files(token: str) -> list:
    return request_json("GET", f"{FILES_BASE_URL}/files", token)


def get_file(token: str, file_id: str) -> dict:
    return request_json("GET", f"{FILES_BASE_URL}/files/{file_id}", token)


def delete_file(token: str, file_id: str) -> Any:
    return request_json("DELETE", f"{FILES_BASE_URL}/files/{file_id}", token)


def get_file_chunks(token: str, file_id: str) -> list:
    return request_json("GET", f"{FILES_BASE_URL}/files/{file_id}/chunks", token)


def get_download_url(token: str, file_id: str) -> dict:
    return request_json("GET", f"{FILES_BASE_URL}/files/{file_id}/download-url", token)


def get_job_status(token: str, job_id: str) -> dict:
    return request_json("GET", f"{FILES_BASE_URL}/jobs/{job_id}/status", token)
