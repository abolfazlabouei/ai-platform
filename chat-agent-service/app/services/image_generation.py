"""
Image generation via an OpenRouter image model (Nano Banana by default).

The chat model can't produce images itself, so it gets a `generate_image` tool
(see graphs/tools/image_tools.py). tool_exec_node runs it locally — not through MCP —
by calling generate_image() here.

OpenRouter only returns images when the request sets modalities=["image", "text"],
and puts them in choices[0].message.images[].image_url.url as data: URLs (not in
message.content), which is why this calls the HTTP API directly instead of ChatOpenAI.
"""
from __future__ import annotations

import base64
import uuid

import httpx

from app.core.config import settings
from app.core.media_types import IMAGE_MIMES, normalize_mime
from app.services.media_resolver import load_media
from app.services.object_store import put_media

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ImageGenerationError(RuntimeError):
    pass


async def generate_image(prompt: str, reference_media_ids: list[str] | None = None) -> list[dict]:
    """
    Generates (or, with reference images, edits) images and stores them.
    Returns generated_image blocks: {"type", "media_id", "url", "mime"}.
    """
    content: list[dict] = [{"type": "text", "text": prompt}]
    for media_id in reference_media_ids or []:
        data, mime = await load_media(media_id, None)
        mime = normalize_mime(mime)
        if mime not in IMAGE_MIMES:
            raise ImageGenerationError(f"Reference {media_id} is not an image ({mime})")
        b64 = base64.b64encode(data).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    payload = {
        "model": settings.IMAGE_GEN_MODEL,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

    async with httpx.AsyncClient(timeout=settings.IMAGE_GEN_TIMEOUT_SECONDS) as client:
        resp = await client.post(_OPENROUTER_URL, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise ImageGenerationError(f"Image model returned {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    if body.get("error"):
        raise ImageGenerationError(f"Image model error: {body['error']}")
    message = (body.get("choices") or [{}])[0].get("message") or {}

    blocks: list[dict] = []
    for img in message.get("images") or []:
        data_url = (img.get("image_url") or {}).get("url", "")
        header, _, b64 = data_url.partition(",")
        if not header.startswith("data:") or not b64:
            continue
        mime = normalize_mime(header[5:].split(";")[0]) or "image/png"
        ext = IMAGE_MIMES.get(mime, "png")
        media_id = f"generated/{uuid.uuid4()}.{ext}"
        url = await put_media(media_id, base64.b64decode(b64), mime)
        blocks.append({"type": "generated_image", "media_id": media_id, "url": url, "mime": mime})

    if not blocks:
        text = message.get("content") or "no image returned"
        raise ImageGenerationError(f"Image model returned no image: {str(text)[:300]}")
    return blocks
