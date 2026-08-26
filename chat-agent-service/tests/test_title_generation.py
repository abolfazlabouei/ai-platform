"""
Tests for automatic conversation title generation — applies identically to
ad-hoc and agent conversations, triggered only on the conversation's first
message (i.e. while Conversation.title is still None).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_service import ChatService
from app.services.title_service import _extract_text, _fallback_title, generate_title


def test_extract_text_pulls_only_text_blocks():
    blocks = [
        {"type": "image", "url": "http://example.com/x.png"},
        {"type": "text", "text": "hello"},
        {"type": "text", "text": "world"},
    ]
    assert _extract_text(blocks) == "hello world"


def test_fallback_title_truncates_long_input():
    long_text = " ".join(["word"] * 20)
    fallback = _fallback_title(long_text)
    assert fallback.endswith("…")
    assert len(fallback.split()) == 8


def test_fallback_title_short_input_no_ellipsis():
    assert _fallback_title("hi there") == "hi there"


@pytest.mark.asyncio
async def test_generate_title_returns_placeholder_for_non_text_first_message():
    result = await generate_title([{"type": "image", "url": "http://example.com/x.png"}])
    assert result == "New conversation"


@pytest.mark.asyncio
async def test_maybe_generate_title_skips_when_title_already_set():
    service = ChatService.__new__(ChatService)
    service.conversation_service = MagicMock()
    service.conversation_service.set_title_if_empty = AsyncMock()

    conversation = MagicMock(title="Existing Title")

    with patch("app.services.chat_service.generate_title", new=AsyncMock()) as gen:
        await service._maybe_generate_title(conversation, [{"type": "text", "text": "second message"}])
        gen.assert_not_called()
        service.conversation_service.set_title_if_empty.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_generate_title_runs_on_first_message():
    service = ChatService.__new__(ChatService)
    service.conversation_service = MagicMock()
    service.conversation_service.set_title_if_empty = AsyncMock()

    conversation = MagicMock(title=None)

    with patch("app.services.chat_service.generate_title", new=AsyncMock(return_value="Generated Title")) as gen:
        await service._maybe_generate_title(conversation, [{"type": "text", "text": "first message"}])
        gen.assert_awaited_once()
        service.conversation_service.set_title_if_empty.assert_awaited_once_with(conversation, "Generated Title")