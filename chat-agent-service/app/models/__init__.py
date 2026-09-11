"""Import all models here so Base.metadata / Alembic autogenerate can discover them."""
from app.models.agent import Agent  # noqa: F401
from app.models.channel_identity import ChannelIdentity  # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.mcp_server import McpServer, McpTool  # noqa: F401
from app.models.mcp_user_connection import McpUserConnection, OAuthConnectionStatus  # noqa: F401
from app.models.message import Message  # noqa: F401
