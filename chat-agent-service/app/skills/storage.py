"""
MinIO/S3 storage for skill files, key layout: <user_id>/<skill_id>/v<version>/<path>
inside SKILLS_BUCKET. Same boto3 pattern as services/object_store.py (blocking calls
run in a thread). A second client signed against S3_PUBLIC_BASE_URL produces
browser-reachable links for binary files.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class SkillStorage(Protocol):
    async def put(self, key: str, data: bytes, mime: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    async def presign(self, key: str) -> str: ...


def file_key(user_id: str, skill_id: object, version: int, path: str) -> str:
    return f"{skill_id_prefix(user_id, skill_id)}v{version}/{path}"


def skill_id_prefix(user_id: str, skill_id: object) -> str:
    return f"{user_id}/{skill_id}/"


class S3SkillStorage:
    def __init__(self) -> None:
        self._clients: dict[str, object] = {}
        self._bucket_ready = False

    def _client(self, endpoint: str):
        if endpoint not in self._clients:
            self._clients[endpoint] = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
                region_name="us-east-1",
            )
        return self._clients[endpoint]

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        client = self._client(settings.S3_ENDPOINT)
        try:
            client.head_bucket(Bucket=settings.SKILLS_BUCKET)
        except ClientError:
            client.create_bucket(Bucket=settings.SKILLS_BUCKET)
        self._bucket_ready = True

    def _put(self, key: str, data: bytes, mime: str) -> None:
        self._ensure_bucket()
        self._client(settings.S3_ENDPOINT).put_object(
            Bucket=settings.SKILLS_BUCKET, Key=key, Body=data, ContentType=mime
        )

    def _get(self, key: str) -> bytes:
        return self._client(settings.S3_ENDPOINT).get_object(Bucket=settings.SKILLS_BUCKET, Key=key)["Body"].read()

    def _delete_prefix(self, prefix: str) -> None:
        client = self._client(settings.S3_ENDPOINT)
        token = None
        while True:
            kwargs = {"Bucket": settings.SKILLS_BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = client.list_objects_v2(**kwargs)
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=settings.SKILLS_BUCKET, Delete={"Objects": keys})
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")

    async def put(self, key: str, data: bytes, mime: str) -> None:
        await asyncio.to_thread(self._put, key, data, mime)

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._get, key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NoSuchBucket"):
                raise KeyError(key) from exc
            raise

    async def delete_prefix(self, prefix: str) -> None:
        try:
            await asyncio.to_thread(self._delete_prefix, prefix)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("NoSuchBucket", "404"):
                raise

    async def presign(self, key: str) -> str:
        return await asyncio.to_thread(
            self._client(settings.S3_PUBLIC_BASE_URL).generate_presigned_url,
            "get_object",
            Params={"Bucket": settings.SKILLS_BUCKET, "Key": key},
            ExpiresIn=settings.SKILLS_FILE_URL_TTL_SECONDS,
        )


_storage: SkillStorage | None = None


def get_storage() -> SkillStorage:
    global _storage
    if _storage is None:
        _storage = S3SkillStorage()
    return _storage
