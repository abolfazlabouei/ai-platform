"""
S3/MinIO-compatible client wrapper. Exposes both a sync interface (used inside
Celery tasks, which run outside the asyncio event loop) and a thin async wrapper
(used by the FastAPI upload endpoint) around the same underlying boto3 client.
"""
from __future__ import annotations

import asyncio
from functools import partial

import boto3

from app.core.config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
        for bucket in (settings.S3_BUCKET_RAW, settings.S3_BUCKET_IMAGES):
            try:
                _client.head_bucket(Bucket=bucket)
            except Exception:  # noqa: BLE001 — bucket doesn't exist yet, create it
                _client.create_bucket(Bucket=bucket)
    return _client


# --- sync API (Celery tasks) ---


def put_object_sync(bucket: str, key: str, data: bytes, content_type: str | None = None) -> str:
    client = _get_client()
    kwargs = {"Bucket": bucket, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type
    client.put_object(**kwargs)
    return f"{settings.S3_PUBLIC_BASE_URL}/{bucket}/{key}"


def get_object_sync(bucket: str, key: str) -> bytes:
    client = _get_client()
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


def delete_object_sync(bucket: str, key: str) -> None:
    client = _get_client()
    client.delete_object(Bucket=bucket, Key=key)


def presigned_url_sync(bucket: str, key: str, expires_seconds: int = 3600) -> str:
    client = _get_client()
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_seconds
    )


# --- async API (FastAPI request handlers) ---


async def put_object(bucket: str, key: str, data: bytes, content_type: str | None = None) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(put_object_sync, bucket, key, data, content_type))


async def delete_object(bucket: str, key: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(delete_object_sync, bucket, key))


async def presigned_url(bucket: str, key: str, expires_seconds: int = 3600) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(presigned_url_sync, bucket, key, expires_seconds))
