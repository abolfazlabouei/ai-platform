"""
input_normalizer node.

Runs first on every turn. Its job is purely to make sure the latest human message's
content_blocks (text/image/audio references coming from the API layer) are converted
into a proper LangChain HumanMessage with multimodal content parts, so llm_node can
just hand `state["messages"]` straight to the model.

Image/audio blocks carry a `url` (already resolved by chat_service via file-service),
which is turned into the provider-native multimodal content part.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from app.graphs.state import GraphState


def _block_to_content_part(block: dict) -> dict:
    btype = block.get("type")
    if btype == "text":
        return {"type": "text", "text": block["text"]}
    if btype == "image":
        return {"type": "image_url", "image_url": {"url": block["url"]}}
    if btype == "audio":
        # Providers that accept audio (per this platform's model) use an "input_audio" part;
        # url is a pre-signed/public link resolved by file-processing-service.
        return {"type": "input_audio", "input_audio": {"url": block["url"], "mime": block.get("mime")}}
    raise ValueError(f"Unsupported input content block type: {btype}")


async def input_normalizer(state: GraphState) -> dict[str, Any]:
    incoming_blocks = state.get("_incoming_blocks")  # injected by chat_service before invoke
    if not incoming_blocks:
        return {}

    content_parts = [_block_to_content_part(b) for b in incoming_blocks]
    human_message = HumanMessage(content=content_parts)
    return {"messages": [human_message]}
