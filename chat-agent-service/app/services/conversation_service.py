"""conversation_service: persistence-facing logic for listing/deleting conversations and history."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.repositories.conversation_repo import ConversationRepo
from app.repositories.message_repo import MessageRepo


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conv_repo = ConversationRepo(db)
        self.msg_repo = MessageRepo(db)

    async def get_or_create(
        self,
        conversation_id: uuid.UUID | None,
        user_id: str,
        agent_id: uuid.UUID | None,
        mode: str,
        channel: str,
        runtime_config: dict,
    ) -> Conversation:
        if conversation_id:
            conv = await self.conv_repo.get(conversation_id)
            if conv:
                return conv
        return await self.conv_repo.create(
            id=conversation_id or uuid.uuid4(),
            user_id=user_id,
            agent_id=agent_id,
            mode=mode,
            channel=channel,
            runtime_config=runtime_config,
        )

    async def list_for_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return await self.conv_repo.list_for_user(user_id, limit, offset)

    async def get_history(self, conversation_id: uuid.UUID, limit: int = 50) -> list[Message]:
        return await self.msg_repo.list_for_conversation(conversation_id, limit)

    async def record_message(self, conversation_id: uuid.UUID, role: MessageRole, content_blocks: list, **meta):
        return await self.msg_repo.add(
            conversation_id=conversation_id, role=role, content_blocks=content_blocks, extra_metadata=meta
        )

    async def set_title_if_empty(self, conversation: Conversation, title: str) -> Conversation | None:
        """
        Sets `conversation.title` only if it's still unset. Used by title_service
        right after the first user message of a NEW conversation (ad-hoc or agent)
        so a conversation only ever gets its title generated once, regardless of
        how many turns follow. Returns None (no-op) if a title already exists —
        callers can safely call this on every turn without needing to track
        "is this the first message" themselves.
        """
        if conversation.title is not None:
            return None
        return await self.conv_repo.update(conversation, title=title)

    async def delete(self, conversation: Conversation) -> None:
        await self.conv_repo.delete(conversation)
