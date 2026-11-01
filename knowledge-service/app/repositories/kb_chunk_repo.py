"""
Async queries for KBChunk — the Postgres full-text (lexical) counterpart to
vector_store.py's dense Qdrant search.
"""
from __future__ import annotations

import re
import uuid
from functools import reduce

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.kb_chunk import KBChunk
from app.services.text_normalize import query_terms

_QUOTED = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"")


class KBChunkRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def lexical_search(self, kb_ids: list[str], query: str, top_k: int) -> list[dict]:
        """Ranks chunks of the given knowledge bases by ts_rank_cd against the
        query's content words (OR-combined), plus a boost for chunks containing a
        phrase the user put in quotes («…», “…” or "...")."""
        kb_uuids = []
        for kb_id in kb_ids:
            try:
                kb_uuids.append(uuid.UUID(kb_id))
            except ValueError:
                continue
        if not kb_uuids or top_k <= 0:
            return []

        terms = query_terms(query)
        if not terms:
            return []
        tsquery = reduce(
            lambda a, b: a.op("||")(b),
            [func.plainto_tsquery("simple", term) for term in terms],
        )
        rank_expr = func.ts_rank_cd(KBChunk.content_tsv, tsquery)

        for groups in _QUOTED.findall(query):
            phrase = next((g for g in groups if g), "").strip()
            if not phrase:
                continue
            rank_expr = rank_expr + case(
                (KBChunk.content_tsv.op("@@")(func.phraseto_tsquery("simple", phrase)), settings.LEXICAL_PHRASE_BOOST),
                else_=0.0,
            )

        rank = rank_expr.label("rank")
        stmt = (
            select(KBChunk, rank)
            .where(KBChunk.knowledge_base_id.in_(kb_uuids))
            .where(KBChunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(top_k)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "score": float(score),
                "chunk_id": str(chunk.chunk_id),
                "file_id": str(chunk.file_id),
                "knowledge_base_id": str(chunk.knowledge_base_id),
                "content": chunk.content,
                "type": chunk.type,
                "metadata": {},
            }
            for chunk, score in result.all()
        ]
