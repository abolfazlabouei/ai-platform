"""
Built-in (non-MCP) tools bound to the chat model. Only the schema lives here; the
call itself is executed by tool_exec_node, which needs graph state to record the
generated images for the turn.
"""
from __future__ import annotations

from langchain_core.tools import tool

GENERATE_IMAGE_TOOL = "generate_image"


@tool(GENERATE_IMAGE_TOOL)
def generate_image_tool(prompt: str, reference_media_ids: list[str] | None = None) -> str:
    """Generate a new image, or edit existing images, and show it to the user.

    Use this whenever the user asks you to draw, create, design, or edit a picture.

    Args:
        prompt: Detailed description of the image to create, or of the edit to make.
            Write it in English for best results.
        reference_media_ids: media_ids of images to edit or use as reference (from
            "[attached image media_id=...]" markers or earlier generate_image results).
            Omit to create an image from scratch.
    """
    raise NotImplementedError("Executed by tool_exec_node")


def builtin_tools() -> list:
    from app.core.config import settings

    return [generate_image_tool] if settings.IMAGE_GEN_ENABLED else []
