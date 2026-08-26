"""
image_chunker: uploads an extracted image's raw bytes to object storage and
returns the (storage_key, caption) pair used to build an image-type Chunk.
Captioning is intentionally minimal here (filename-derived placeholder) — if a
vision-capable captioning step is desired later, it plugs in right here without
touching any other module, since this is the single place image chunks are built.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.storage.object_store import put_object_sync


def chunk_image(image_bytes: bytes, content_type: str, source_filename: str) -> dict:
    ext = content_type.split("/")[-1] if "/" in content_type else "bin"
    key = f"{uuid.uuid4()}.{ext}"
    put_object_sync(settings.S3_BUCKET_IMAGES, key, image_bytes, content_type)

    caption = f"[Embedded image: {source_filename}]"
    return {"storage_key": key, "content": caption}
