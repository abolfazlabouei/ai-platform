"""chat-agent-service client: chat, agents, conversations, tool approval, MCP servers, media, KB proxy."""
from typing import Any, Iterator, Optional

from config import CHAT_BASE_URL

from .base import request_json, stream_sse, upload_file


def _chat_body(
    content_text: str,
    conversation_id: Optional[str],
    mcp_server_ids: Optional[list],
    knowledge_base_ids: Optional[list],
    model_provider: Optional[str],
    model_name: Optional[str],
    clinic_id: Optional[str],
) -> dict:
    body: dict[str, Any] = {
        "content_blocks": [{"type": "text", "text": content_text}],
    }
    if conversation_id:
        body["conversation_id"] = conversation_id
    if mcp_server_ids:
        body["mcp_server_ids"] = mcp_server_ids
    if knowledge_base_ids:
        body["knowledge_base_ids"] = knowledge_base_ids
    if model_provider:
        body["model_provider"] = model_provider
    if model_name:
        body["model_name"] = model_name
    if clinic_id:
        body["clinic_id"] = clinic_id
    return body


def chat_complete(token: str, **kwargs) -> dict:
    return request_json("POST", f"{CHAT_BASE_URL}/chat/complete", token, json_body=_chat_body(**kwargs))


def chat_stream(token: str, **kwargs) -> Iterator[tuple[str, dict]]:
    yield from stream_sse(f"{CHAT_BASE_URL}/chat/stream", token, _chat_body(**kwargs))


def agent_chat_complete(
    token: str, agent_id: str, content_text: str, conversation_id: Optional[str], clinic_id: Optional[str] = None
) -> dict:
    body: dict[str, Any] = {"content_blocks": [{"type": "text", "text": content_text}]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    if clinic_id:
        body["clinic_id"] = clinic_id
    return request_json("POST", f"{CHAT_BASE_URL}/agents/{agent_id}/chat/complete", token, json_body=body)


def agent_chat_stream(
    token: str, agent_id: str, content_text: str, conversation_id: Optional[str], clinic_id: Optional[str] = None
) -> Iterator[tuple[str, dict]]:
    body: dict[str, Any] = {"content_blocks": [{"type": "text", "text": content_text}]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    if clinic_id:
        body["clinic_id"] = clinic_id
    yield from stream_sse(f"{CHAT_BASE_URL}/agents/{agent_id}/chat/stream", token, body)


def create_agent(token: str, agent: dict) -> dict:
    return request_json("POST", f"{CHAT_BASE_URL}/agents", token, json_body=agent)


def list_agents(token: str, is_composable: Optional[bool] = None) -> list:
    params = {"is_composable": is_composable} if is_composable is not None else None
    return request_json("GET", f"{CHAT_BASE_URL}/agents", token, params=params)


def get_agent(token: str, agent_id: str) -> dict:
    return request_json("GET", f"{CHAT_BASE_URL}/agents/{agent_id}", token)


def update_agent(token: str, agent_id: str, patch: dict) -> dict:
    return request_json("PATCH", f"{CHAT_BASE_URL}/agents/{agent_id}", token, json_body=patch)


def delete_agent(token: str, agent_id: str) -> Any:
    return request_json("DELETE", f"{CHAT_BASE_URL}/agents/{agent_id}", token)


def list_conversations(token: str, limit: int = 50, offset: int = 0) -> list:
    return request_json("GET", f"{CHAT_BASE_URL}/conversations", token, params={"limit": limit, "offset": offset})


def get_conversation_messages(token: str, conversation_id: str, limit: int = 50) -> list:
    return request_json(
        "GET", f"{CHAT_BASE_URL}/conversations/{conversation_id}/messages", token, params={"limit": limit}
    )


def delete_conversation(token: str, conversation_id: str) -> Any:
    return request_json("DELETE", f"{CHAT_BASE_URL}/conversations/{conversation_id}", token)


def tool_approval_stream(token: str, conversation_id: str, decisions: dict) -> Iterator[tuple[str, dict]]:
    yield from stream_sse(
        f"{CHAT_BASE_URL}/conversations/{conversation_id}/tool-approval", token, {"decisions": decisions}
    )


def create_mcp_server(token: str, server: dict) -> dict:
    return request_json("POST", f"{CHAT_BASE_URL}/mcp-servers", token, json_body=server)


def list_mcp_servers(token: str) -> list:
    return request_json("GET", f"{CHAT_BASE_URL}/mcp-servers", token)


def list_mcp_server_tools(token: str, server_id: str) -> list:
    return request_json("GET", f"{CHAT_BASE_URL}/mcp-servers/{server_id}/tools", token)


def test_mcp_server_connection(token: str, server_id: str) -> list:
    return request_json("POST", f"{CHAT_BASE_URL}/mcp-servers/{server_id}/test-connection", token)


def update_mcp_tool(token: str, server_id: str, tool_id: str, patch: dict) -> dict:
    return request_json(
        "PATCH", f"{CHAT_BASE_URL}/mcp-servers/{server_id}/tools/{tool_id}", token, json_body=patch
    )


def delete_mcp_server(token: str, server_id: str) -> Any:
    return request_json("DELETE", f"{CHAT_BASE_URL}/mcp-servers/{server_id}", token)


def list_knowledge_bases_proxy(token: str) -> list:
    return request_json("GET", f"{CHAT_BASE_URL}/knowledge-bases", token)


def upload_media(token: str, filename: str, file_bytes: bytes) -> dict:
    return upload_file(f"{CHAT_BASE_URL}/media/upload", token, filename, file_bytes)


def get_media_url(token: str, media_id: str) -> dict:
    return request_json("GET", f"{CHAT_BASE_URL}/media/{media_id}", token)
