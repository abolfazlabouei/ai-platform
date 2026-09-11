"""
McpUserConnection: a single user's OAuth2 connection to a specific MCP server
that requires per-user auth (e.g. Google Calendar, Gmail). One row per
(mcp_server_id, user_id) pair — enforced by a unique constraint. Tokens are
stored encrypted at rest (see app/core/encryption.py); never store them in
plaintext, never log them, never include them in any API response body.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.mcp_server import McpServer


class OAuthConnectionStatus(str, enum.Enum):
    CONNECTED = "connected"
    EXPIRED = "expired"        # refresh_token itself failed/was revoked by the provider
    DISCONNECTED = "disconnected"  # user explicitly disconnected


class McpUserConnection(Base):
    __tablename__ = "mcp_user_connections"
    __table_args__ = (UniqueConstraint("mcp_server_id", "user_id", name="uq_mcp_server_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    # Encrypted at rest via app.core.encryption.encrypt_str / decrypt_str.
    # Stored as opaque base64 ciphertext strings, never plaintext.
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # space-separated, as returned by provider

    status: Mapped[OAuthConnectionStatus] = mapped_column(
        Enum(OAuthConnectionStatus, name="oauth_connection_status"),
        default=OAuthConnectionStatus.CONNECTED,
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    server: Mapped["McpServer"] = relationship()
