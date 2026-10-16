"""
Converts the raw LangGraph event stream (from chat_service.run_turn /
resume_tool_approval) into Server-Sent-Events frames consumed by the frontend.

LangGraph's astream_events (v2) emits a fine-grained event stream (on_chat_model_stream,
on_tool_start, on_tool_end, ...). We translate the subset that matters to the frontend
into the StreamEventType vocabulary and drop the rest (kept for future flexibility to
surface more, e.g. reasoning traces, without changing the frontend contract).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from app.streaming.event_types import StreamEventType


def _sse_frame(event_type: StreamEventType, data: dict) -> str:
    return f"event: {event_type.value}\ndata: {json.dumps(data, default=str)}\n\n"


async def to_sse(event_stream, conversation_id: str | None = None):
    if conversation_id:
        yield _sse_frame(StreamEventType.CONVERSATION_INFO, {"conversation_id": conversation_id})
    sent_images: set[str] = set()
    try:
        async for event in event_stream:
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                text = getattr(chunk, "content", None) if chunk else None
                if text:
                    if isinstance(text, list):
                        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                    if text:
                        yield _sse_frame(StreamEventType.TOKEN, {"text": text})

            elif kind == "on_tool_start":
                yield _sse_frame(
                    StreamEventType.TOOL_CALL,
                    {"tool_name": event.get("name"), "input": event["data"].get("input")},
                )

            elif kind == "on_tool_end":
                yield _sse_frame(
                    StreamEventType.TOOL_RESULT,
                    {"tool_name": event.get("name"), "output": str(event["data"].get("output"))},
                )

            # generate_image runs inside tool_exec_node (not as a LangChain tool), so
            # images are picked up from that node's state update
            elif kind == "on_chain_end" and event.get("name") == "tool_exec_node":
                output = event["data"].get("output")
                for img in (output or {}).get("generated_images", []) if isinstance(output, dict) else []:
                    if img.get("media_id") not in sent_images:
                        sent_images.add(img.get("media_id"))
                        yield _sse_frame(StreamEventType.IMAGE, img)

            # LangGraph surfaces a paused graph (hitl_gate's interrupt()) as a special
            # event/task result rather than a normal node event; the exact shape depends
            # on the installed langgraph version. Detect it defensively here.
            elif kind == "on_chain_stream" and isinstance(event["data"].get("chunk"), dict):
                chunk = event["data"]["chunk"]
                if "__interrupt__" in chunk:
                    interrupt_payload = chunk["__interrupt__"][0].value
                    yield _sse_frame(StreamEventType.TOOL_APPROVAL_REQUIRED, interrupt_payload)

        yield _sse_frame(StreamEventType.DONE, {})

    except Exception as exc:  # noqa: BLE001
        yield _sse_frame(StreamEventType.ERROR, {"message": str(exc)})
