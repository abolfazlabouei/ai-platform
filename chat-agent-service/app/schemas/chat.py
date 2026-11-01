"""Request/response schemas for /chat and /agents/{id}/chat endpoints."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.skill import SkillRef
from app.core.media_types import AUDIO_FORMATS, IMAGE_MIMES, normalize_mime
from shared_schemas.content_blocks import AudioBlock, ContentBlock, ImageBlock, TextBlock

_INPUT_BLOCK_TYPES = (TextBlock, ImageBlock, AudioBlock)


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None  # omit to start a new conversation
    content_blocks: list[ContentBlock]

    # Only meaningful for ad-hoc chat (ignored/overridable-by-admin on agent chat):
    mcp_server_ids: list[uuid.UUID] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    skill_ids: list[SkillRef] = Field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None

    @field_validator("content_blocks")
    @classmethod
    def _validate_input_blocks(cls, blocks: list) -> list:
        if not blocks:
            raise ValueError("content_blocks must not be empty")
        for b in blocks:
            if not isinstance(b, _INPUT_BLOCK_TYPES):
                raise ValueError(f"'{b.type}' blocks can't be sent as user input; use text, image or audio")
            if isinstance(b, TextBlock):
                continue
            url = b.url or ""
            if not b.media_id and not url.startswith("data:") and not (
                isinstance(b, ImageBlock) and url.startswith(("http://", "https://"))
            ):
                raise ValueError(
                    f"{b.type} block needs a media_id from /media/upload or a data: URL"
                    + (" (or an http(s) URL)" if isinstance(b, ImageBlock) else "")
                )
            if b.mime:
                allowed = IMAGE_MIMES if isinstance(b, ImageBlock) else AUDIO_FORMATS
                if normalize_mime(b.mime) not in allowed:
                    raise ValueError(f"Unsupported {b.type} type '{b.mime}'")
        return blocks


class ToolApprovalRequest(BaseModel):
    decisions: dict[str, bool]  # tool_call_id -> approve(True)/reject(False)


class ChatCompleteResponse(BaseModel):
    conversation_id: uuid.UUID
    content_blocks: list[ContentBlock]
