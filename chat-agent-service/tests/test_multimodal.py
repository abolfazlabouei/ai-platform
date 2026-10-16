"""
Multimodal input/output without live S3/OpenRouter: media refs are inlined in the
provider's format, request validation rejects non-input blocks, and generate_image
parses OpenRouter's message.images and records results in turn state.
"""
import base64

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.graphs.nodes import tool_exec_node as tool_exec_module
from app.graphs.nodes.input_normalizer import input_normalizer
from app.schemas.chat import ChatRequest
from app.services import image_generation, media_resolver

PNG = b"\x89PNG\r\n\x1a\nfake"
WAV = b"RIFF....WAVEfake"


@pytest.fixture
def fake_store(monkeypatch):
    stored: dict[str, tuple[bytes, str]] = {
        "uploads/u/a.png": (PNG, "image/png"),
        "uploads/u/b.wav": (WAV, "audio/wav"),
    }

    async def get_media(key):
        if key not in stored:
            raise KeyError(key)
        return stored[key]

    async def put_media(key, data, mime):
        stored[key] = (data, mime)
        return f"http://media/{key}"

    media_resolver._cache.clear()
    monkeypatch.setattr(media_resolver, "get_media", get_media)
    monkeypatch.setattr(image_generation, "put_media", put_media)
    return stored


async def test_input_normalizer_stores_refs_and_resets_images():
    state = {
        "_incoming_blocks": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "media_id": "uploads/u/a.png", "url": None, "mime": "image/png"},
        ],
        "generated_images": [{"type": "generated_image", "url": "old"}],
    }
    out = await input_normalizer(state)
    assert out["generated_images"] == []
    parts = out["messages"][0].content
    assert parts[1] == {"type": "media_ref", "kind": "image", "media_id": "uploads/u/a.png", "url": None, "mime": "image/png"}


async def test_inline_media_uses_provider_formats(fake_store):
    msg = HumanMessage(
        content=[
            {"type": "text", "text": "hi"},
            {"type": "media_ref", "kind": "image", "media_id": "uploads/u/a.png", "url": None, "mime": None},
            {"type": "media_ref", "kind": "audio", "media_id": "uploads/u/b.wav", "url": None, "mime": "audio/x-wav"},
            {"type": "media_ref", "kind": "image", "media_id": None, "url": "https://example.com/x.png", "mime": None},
        ]
    )
    [out] = await media_resolver.inline_media([msg])
    types = [p["type"] for p in out.content]
    assert types == ["text", "text", "image_url", "text", "input_audio", "image_url"]
    assert out.content[2]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert out.content[4]["input_audio"] == {"data": base64.b64encode(WAV).decode(), "format": "wav"}
    assert out.content[5]["image_url"]["url"] == "https://example.com/x.png"
    # stored message (checkpointed state) is untouched
    assert msg.content[1]["type"] == "media_ref"


def test_chat_request_rejects_non_input_blocks():
    with pytest.raises(ValidationError):
        ChatRequest(content_blocks=[{"type": "generated_image", "url": "x"}])
    with pytest.raises(ValidationError):
        ChatRequest(content_blocks=[{"type": "audio", "url": "https://example.com/a.mp3"}])
    with pytest.raises(ValidationError):
        ChatRequest(content_blocks=[{"type": "image", "media_id": "m", "mime": "image/tiff"}])
    ChatRequest(content_blocks=[{"type": "text", "text": "hi"}, {"type": "audio", "media_id": "m", "mime": "audio/mpeg"}])


async def test_generate_image_parses_openrouter_images(fake_store, monkeypatch):
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.update(json.loads(request.content))
        data_url = "data:image/png;base64," + base64.b64encode(b"generated").decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "", "images": [{"type": "image_url", "image_url": {"url": data_url}}]}}]},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_generation.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )

    blocks = await image_generation.generate_image("a cat", ["uploads/u/a.png"])
    assert sent["modalities"] == ["image", "text"]
    assert sent["messages"][0]["content"][1]["type"] == "image_url"
    assert len(blocks) == 1 and blocks[0]["media_id"].startswith("generated/")
    assert fake_store[blocks[0]["media_id"]][0] == b"generated"


async def test_tool_exec_runs_generate_image_locally(monkeypatch):
    async def fake_generate(prompt, reference_media_ids):
        return [{"type": "generated_image", "media_id": "generated/x.png", "url": "u", "mime": "image/png"}]

    monkeypatch.setattr(tool_exec_module, "generate_image", fake_generate)
    ai = AIMessage(content="", tool_calls=[{"id": "c1", "name": "generate_image", "args": {"prompt": "cat"}}])
    out = await tool_exec_module.tool_exec_node({"messages": [ai], "generated_images": []})
    assert out["generated_images"][0]["media_id"] == "generated/x.png"
    assert "generated/x.png" in out["messages"][0].content
