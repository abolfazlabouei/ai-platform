"""
Minimal S3/MinIO-compatible client for chat media owned by chat-agent-service:
user image/audio attachments (uploads/...) and model-generated images (generated/...).
(Raw uploaded documents/chunks live in file-processing-service's own object storage.)

Keys contain a random UUID and are served unauthenticated by GET /media/files/{key}
so <img>/<audio> tags can load them directly.
"""
from __future__ import annotations

import asyncio

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

_client = None
_bucket_ready = False


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
    return _client


def _ensure_bucket(client) -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET_GENERATED)
    except ClientError:
        client.create_bucket(Bucket=settings.S3_BUCKET_GENERATED)
    _bucket_ready = True


def _put(key: str, data: bytes, mime: str) -> None:
    client = _get_client()
    _ensure_bucket(client)
    client.put_object(Bucket=settings.S3_BUCKET_GENERATED, Key=key, Body=data, ContentType=mime)


def _get(key: str) -> tuple[bytes, str]:
    obj = _get_client().get_object(Bucket=settings.S3_BUCKET_GENERATED, Key=key)
    return obj["Body"].read(), obj.get("ContentType") or "application/octet-stream"


def media_url(key: str) -> str:
    return f"{settings.MEDIA_PUBLIC_BASE_URL}/{key}"


async def put_media(key: str, data: bytes, mime: str) -> str:
    """Stores the object and returns its client-facing URL."""
    await asyncio.to_thread(_put, key, data, mime)
    return media_url(key)


async def get_media(key: str) -> tuple[bytes, str]:
    """Returns (bytes, mime). Raises KeyError if the object doesn't exist."""
    try:
        return await asyncio.to_thread(_get, key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NoSuchBucket"):
            raise KeyError(key) from exc
        raise
