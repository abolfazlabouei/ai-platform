"""
output_formatter node.

Runs at the end of a turn. Scans the final AIMessage for any provider-native
generated-image parts (this platform's model can both understand and generate
images), uploads each to object storage, and replaces the inline payload with a
lightweight reference: {url, thumbnail_base64}. Keeps SSE/API payloads small and
lets the frontend lazy-load full images from the URL.
"""
from __future__ import annotations

import base64
import io
import uuid
from typing import Any

from app.graphs.state import GraphState
from app.services.object_store import upload_generated_image


def _make_thumbnail_base64(image_bytes: bytes, max_size: int = 64) -> str:
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def output_formatter(state: GraphState) -> dict[str, Any]:
    last_ai_message = state["messages"][-1]
    content = last_ai_message.content
    if isinstance(content, str):
        return {}

    generated_images = []
    for part in content:
        if isinstance(part, dict) and part.get("type") in ("image", "output_image"):
            raw_b64 = part.get("data") or part.get("base64")
            if not raw_b64:
                continue
            image_bytes = base64.b64decode(raw_b64)
            key = f"{uuid.uuid4()}.png"
            url = await upload_generated_image(key, image_bytes)
            generated_images.append(
                {
                    "type": "generated_image",
                    "url": url,
                    "mime": "image/png",
                    "thumbnail_base64": _make_thumbnail_base64(image_bytes),
                }
            )

    if not generated_images:
        return {}
    return {"generated_images": generated_images}
