import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.mcp_server import McpServer, McpTool, McpTransport, ToolApprovalStatus
from app.services.chat_service import ChatService


@pytest.fixture
def oauth_server():
    server = MagicMock(spec=McpServer)
    server.id = uuid.uuid4()
    server.name = "google-calendar"
    server.transport = McpTransport.SSE
    server.url = "http://localhost:8000/sse"
    server.auth_config = {
        "type": "oauth2_per_user",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    }
    return server


@pytest.fixture
def calendar_tool(oauth_server):
    tool = MagicMock(spec=McpTool)
    tool.id = uuid.uuid4()
    tool.mcp_server_id = oauth_server.id
    tool.tool_name = "calendar_create_event"
    tool.description = "Create a calendar event"
    tool.approval_status = ToolApprovalStatus.APPROVED
    tool.requires_hitl = False
    return tool


@pytest.mark.asyncio
async def test_oauth_unconnected_tool_excluded_and_context_injected(oauth_server, calendar_tool):
    mock_db = AsyncMock()
    chat_service = ChatService(mock_db)

    conv_id = uuid.uuid4()
    user_id = "user_test_123"

    with (
        patch("app.services.chat_service.get_approved_tools", new_callable=AsyncMock) as mock_get_tools,
        patch.object(chat_service.mcp_repo, "get_server", new_callable=AsyncMock) as mock_get_server,
        patch("app.services.oauth_service.OAuthService.get_valid_access_token", new_callable=AsyncMock) as mock_get_token,
        patch("app.mcp_manager.client_pool.McpClientPool.as_langchain_tools", new_callable=AsyncMock) as mock_as_tools,
    ):
        mock_get_tools.return_value = [calendar_tool]
        mock_get_server.return_value = oauth_server
        # User has NOT connected
        mock_get_token.return_value = None

        runtime = await chat_service._build_runtime_config(
            conversation_id=conv_id,
            user_id=user_id,
            agent=None,
            mcp_server_ids=[str(oauth_server.id)],
            knowledge_base_ids=[],
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            system_prompt_override="Base prompt",
        )

        # Tool must be excluded from bound_tools
        assert len(runtime["bound_tools"]) == 0
        mock_as_tools.assert_not_called()

        # oauth_missing_context note must be injected
        missing_context = runtime.get("oauth_missing_context")
        assert missing_context is not None
        assert "google-calendar" in missing_context
        assert "not connected their account" in missing_context


@pytest.mark.asyncio
async def test_oauth_connected_tool_bound_normally(oauth_server, calendar_tool):
    mock_db = AsyncMock()
    chat_service = ChatService(mock_db)

    conv_id = uuid.uuid4()
    user_id = "user_test_123"

    fake_langchain_tool = MagicMock()
    fake_langchain_tool.name = "calendar_create_event"

    with (
        patch("app.services.chat_service.get_approved_tools", new_callable=AsyncMock) as mock_get_tools,
        patch.object(chat_service.mcp_repo, "get_server", new_callable=AsyncMock) as mock_get_server,
        patch("app.services.oauth_service.OAuthService.get_valid_access_token", new_callable=AsyncMock) as mock_get_token,
        patch("app.mcp_manager.client_pool.McpClientPool.as_langchain_tools", new_callable=AsyncMock) as mock_as_tools,
    ):
        mock_get_tools.return_value = [calendar_tool]
        mock_get_server.return_value = oauth_server
        # User IS connected
        mock_get_token.return_value = "ya29.valid_token_xyz"
        mock_as_tools.return_value = [fake_langchain_tool]

        runtime = await chat_service._build_runtime_config(
            conversation_id=conv_id,
            user_id=user_id,
            agent=None,
            mcp_server_ids=[str(oauth_server.id)],
            knowledge_base_ids=[],
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            system_prompt_override="Base prompt",
        )

        # Tool must be bound
        assert len(runtime["bound_tools"]) == 1
        assert runtime["bound_tools"][0].name == "calendar_create_event"
        # No missing context
        assert runtime.get("oauth_missing_context") is None
