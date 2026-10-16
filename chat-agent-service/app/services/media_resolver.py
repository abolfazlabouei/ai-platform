"""
Turns chat media references into provider-native content parts.

HumanMessages in graph state only hold lightweight references
({"type": "media_ref", "kind": "image"|"audio", "media_id"?, "url"?, "mime"?}) so the
Postgres checkpointer doesn't re-serialize base64 payloads on every step. Right before
a model call, llm_node swaps each reference for an inline part:

  image -> {"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}
  audio -> {"type": "input_audio", "input_audio": {"data": "<base64>", "format": "wav"|...}}

Uploaded media is always inlined because the provider can't reach MinIO (internal
hostname). External image URLs are passed through for the provider to fetch; we never
download client-supplied URLs ourselves (SSRF), so audio must be uploaded or a data: URL.
"""
from __future__ import annotations

import base64
from collections import OrderedDict

from langchain_core.messages import BaseMessage, HumanMessage

from app.core.media_types import AUDIO_FORMATS, IMAGE_MIMES, normalize_mime
from app.services.object_store import get_media

_CACHE_SIZE = 32
_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()


def media_ref_part(block: dict) -> dict:
    """API content block (image/audio) -> reference part stored in the HumanMessage."""
    return {
        "type": "media_ref",
        "kind": block["type"],
        "media_id": block.get("media_id"),
        "url": block.get("url"),
        "mime": block.get("mime"),
    }


async def load_media(media_id: str | None, url: str | None) -> tuple[bytes, str]:
    """Returns (bytes, mime) for a media reference from our bucket or a data: URL."""
    cache_key = media_id or url
    if cache_key in _cache:
        _cache.move_to_end(cache_key)
        return _cache[cache_key]

    if media_id:
        data, mime = await get_media(media_id)
    elif url and url.startswith("data:"):
        header, _, payload = url.partition(",")
        data, mime = base64.b64decode(payload), header[5:].split(";")[0]
    else:
        raise ValueError("Media must be a media_id from /media/upload or a data: URL")

    _cache[cache_key] = (data, mime)
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return data, mime


async def _to_model_parts(part: dict) -> list[dict]:
    kind = part["kind"]
    url = part.get("url") or ""
    if kind == "image" and not part.get("media_id") and url.startswith(("http://", "https://")):
        return [{"type": "image_url", "image_url": {"url": url}}]

    data, stored_mime = await load_media(part.get("media_id"), part.get("url"))
    mime = normalize_mime(part.get("mime") or stored_mime)
    b64 = base64.b64encode(data).decode()

    parts: list[dict] = []
    if part.get("media_id"):
        # lets the model pass this image to generate_image as a reference
        parts.append({"type": "text", "text": f"[attached {kind} media_id={part['media_id']}]"})

    if kind == "image":
        if mime not in IMAGE_MIMES:
            raise ValueError(f"Unsupported image type: {mime}")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    elif kind == "audio":
        fmt = AUDIO_FORMATS.get(mime)
        if fmt is None:
            raise ValueError(f"Unsupported audio type: {mime}")
        parts.append({"type": "input_audio", "input_audio": {"data": b64, "format": fmt}})
    else:
        raise ValueError(f"Unsupported media kind: {kind}")
    return parts


async def inline_media(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Copies of `messages` with every media_ref part replaced by inline model parts."""
    out: list[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, HumanMessage) or isinstance(msg.content, str):
            out.append(msg)
            continue
        if not any(isinstance(p, dict) and p.get("type") == "media_ref" for p in msg.content):
            out.append(msg)
            continue

        content: list = []
        for p in msg.content:
            if isinstance(p, dict) and p.get("type") == "media_ref":
                content.extend(await _to_model_parts(p))
            else:
                content.append(p)
        out.append(msg.model_copy(update={"content": content}))
    return out
