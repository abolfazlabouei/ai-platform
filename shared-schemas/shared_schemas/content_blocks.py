"""
Canonical content-block types used in every Message across all services/gateways.
This is the single source of truth for multimodal payload shape — chat-agent-service,
file-processing-service, knowledge-service, and every gateway import this module
instead of redefining the shape locally.

Design notes:
  - Large binary payloads (images/audio) are referenced by URL/media_id, not inlined,
    except for small thumbnails used for immediate UI preview.
  - `type` is a discriminator field so this can be used as a tagged union everywhere
    (Pydantic discriminated union, TypeScript-friendly on the frontend, etc).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    """Reference to an image already uploaded via file-processing-service /media/upload."""
    type: Literal["image"] = "image"
    media_id: str | None = None
    url: str | None = None
    mime: str | None = None


class AudioBlock(BaseModel):
    """Reference to an audio clip already uploaded via file-processing-service /media/upload."""
    type: Literal["audio"] = "audio"
    media_id: str | None = None
    url: str | None = None
    mime: str | None = None
    duration_seconds: float | None = None


class GeneratedImageBlock(BaseModel):
    """
    Model-generated image in an assistant response. Prefer URL + small thumbnail
    over full base64 to keep SSE/API payloads light; full base64 is only included
    when explicitly requested (?format=base64).
    """
    type: Literal["generated_image"] = "generated_image"
    url: str
    mime: str = "image/png"
    width: int | None = None
    height: int | None = None
    thumbnail_base64: str | None = None
    base64: str | None = None  # only populated when explicitly requested


class ToolCallBlock(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    server_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    tool_name: str
    is_error: bool = False
    content: str | dict | list


ContentBlock = Annotated[
    Union[TextBlock, ImageBlock, AudioBlock, GeneratedImageBlock, ToolCallBlock, ToolResultBlock],
    Field(discriminator="type"),
]
