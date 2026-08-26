"""SSE event type discriminators emitted by /chat/stream and /agents/{id}/chat/stream."""
from __future__ import annotations

import enum


class StreamEventType(str, enum.Enum):
    TOKEN = "token"                             # incremental assistant text
    TOOL_CALL = "tool_call"                      # model requested a tool call
    TOOL_RESULT = "tool_result"                  # tool execution finished
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"  # graph paused for HITL
    IMAGE = "image"                              # a generated_image block is ready
    ERROR = "error"
    DONE = "done"
    CONVERSATION_INFO = "conversation_info"
