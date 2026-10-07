"""
image_chunker: uploads an (already normalized, PNG) image to object storage and
returns the storage_key. The searchable text of an image chunk is its vision-model
description (see app/workers/vision.py and tasks._caption_images) — images that
couldn't be described are not turned into chunks at all, because a placeholder
like "[Embedded image: image1.png]" carries no meaning and only pollutes retrieval.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.storage.object_store import put_object_sync


def store_image(png_bytes: bytes) -> str:
    key = f"{uuid.uuid4()}.png"
    put_object_sync(settings.S3_BUCKET_IMAGES, key, png_bytes, "image/png")
    return key
