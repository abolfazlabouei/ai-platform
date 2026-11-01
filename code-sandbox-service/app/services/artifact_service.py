"""
ArtifactService: files the program wrote to /workspace/outputs/ during an
execution are copied out (through exec stdout — see docker_backend) and uploaded to
MinIO under <session_id>/<execution_id>/<name>. Browser-openable presigned URLs are
signed against S3_PUBLIC_BASE_URL (a second boto3 client, used only for signing —
presigning makes no network call).
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import posixpath
from functools import partial

import boto3
from botocore.config import Config

from app.core.config import Settings, settings as default_settings
from app.sandbox.executor import ExecutionError, Executor
from app.sandbox.files import OUTPUTS_DIR

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

_clients: dict[str, object] = {}
_bucket_ready = False


def _s3(endpoint: str, cfg: Settings):
    if endpoint not in _clients:
        _clients[endpoint] = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=cfg.S3_ACCESS_KEY,
            aws_secret_access_key=cfg.S3_SECRET_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            region_name="us-east-1",
        )
    return _clients[endpoint]


def _upload_sync(cfg: Settings, key: str, data: bytes, content_type: str) -> str:
    global _bucket_ready
    client = _s3(cfg.S3_ENDPOINT, cfg)
    if not _bucket_ready:
        try:
            client.head_bucket(Bucket=cfg.S3_BUCKET_ARTIFACTS)
        except Exception:  # noqa: BLE001 — bucket doesn't exist yet, create it
            client.create_bucket(Bucket=cfg.S3_BUCKET_ARTIFACTS)
        _bucket_ready = True
    client.put_object(Bucket=cfg.S3_BUCKET_ARTIFACTS, Key=key, Body=data, ContentType=content_type)
    return _s3(cfg.S3_PUBLIC_BASE_URL, cfg).generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg.S3_BUCKET_ARTIFACTS, "Key": key},
        ExpiresIn=cfg.SANDBOX_ARTIFACT_URL_TTL,
    )


class ArtifactService:
    def __init__(self, executor: Executor, cfg: Settings | None = None):
        self.executor = executor
        self.cfg = cfg or default_settings

    async def collect(self, container_id: str, session_id: str, execution_id: str, since_epoch: float) -> list[dict]:
        entries = await self.executor.new_outputs(container_id, since_epoch)
        artifacts: list[dict] = []
        for entry in entries[: self.cfg.SANDBOX_MAX_ARTIFACTS]:
            rel = entry["path"]  # relative to /workspace, e.g. outputs/chart.png
            name = posixpath.relpath(posixpath.join("/workspace", rel), OUTPUTS_DIR)
            ext = posixpath.splitext(name)[1].lower()
            item = {"name": name, "size": entry["size"], "kind": "image" if ext in IMAGE_EXTENSIONS else "file"}
            if entry["size"] > self.cfg.SANDBOX_MAX_ARTIFACT_BYTES:
                item["error"] = f"larger than {self.cfg.SANDBOX_MAX_ARTIFACT_BYTES} bytes, not uploaded"
                artifacts.append(item)
                continue
            try:
                data, truncated = await self.executor.read_file(
                    container_id, rel, self.cfg.SANDBOX_MAX_ARTIFACT_BYTES
                )
                if truncated:
                    raise ExecutionError("file grew past the artifact size limit")
                key = f"{session_id}/{execution_id}/{name}"
                content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                url = await asyncio.get_running_loop().run_in_executor(
                    None, partial(_upload_sync, self.cfg, key, data, content_type)
                )
                item.update({"key": key, "url": url, "content_type": content_type})
            except Exception as exc:  # noqa: BLE001 — one bad file must not fail the execution
                log.warning("artifact %s failed: %s", name, exc)
                item["error"] = "could not be uploaded"
            artifacts.append(item)
        if len(entries) > self.cfg.SANDBOX_MAX_ARTIFACTS:
            artifacts.append(
                {"name": f"... {len(entries) - self.cfg.SANDBOX_MAX_ARTIFACTS} more file(s) skipped", "kind": "note"}
            )
        return artifacts
