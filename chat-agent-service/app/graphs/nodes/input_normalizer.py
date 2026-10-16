"""
input_normalizer node.

Runs first on every turn. Its job is purely to make sure the latest human message's
content_blocks (text/image/audio references coming from the API layer) are converted
into a LangChain HumanMessage, and to reset per-turn state (generated_images).

Image/audio blocks are stored as lightweight media_ref parts (see
services/media_resolver.py); llm_node inlines the actual bytes right before each
model call so base64 payloads never land in the checkpointed state.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from app.graphs.state import GraphState
from app.services.media_resolver import media_ref_part


def _block_to_content_part(block: dict) -> dict:
    btype = block.get("type")
    if btype == "text":
        return {"type": "text", "text": block["text"]}
    if btype in ("image", "audio"):
        return media_ref_part(block)
    raise ValueError(f"Unsupported input content block type: {btype}")


async def input_normalizer(state: GraphState) -> dict[str, Any]:
    incoming_blocks = state.get("_incoming_blocks")  # injected by chat_service before invoke
    if not incoming_blocks:
        return {}

    content_parts = [_block_to_content_part(b) for b in incoming_blocks]
    human_message = HumanMessage(content=content_parts)
    # generated_images is checkpointed; clear the previous turn's images so they
    # aren't re-attached to this turn's assistant message
    return {"messages": [human_message], "generated_images": []}
