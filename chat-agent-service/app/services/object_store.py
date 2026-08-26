"""
Minimal S3/MinIO-compatible client used only for generated-image uploads produced by
output_formatter. (Raw uploaded files/chunks live in file-processing-service's own
object storage — this is a separate, small bucket owned by chat-agent-service.)
"""
from __future__ import annotations

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
    return _client


async def upload_generated_image(key: str, data: bytes) -> str:
    client = _get_client()
    client.put_object(Bucket=settings.S3_BUCKET_GENERATED, Key=key, Body=data, ContentType="image/png")
    return f"{settings.S3_PUBLIC_BASE_URL}/{key}"
