"""
Async queries for KBChunk. the Postgres full-text (lexical) search counterpart
to vector_store.py's dense Qdrant search.
"""
from __future__ import annotations

import re
import uuid
from functools import reduce
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.models.kb_chunk import KBChunk
from app.services.text_normalize import query_terms, bm25_tokens


class KBChunkRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def lexical_search(self, kb_ids: list[str], query: str, top_k: int) -> list[dict]:
        """Ranks chunks in the given knowledge bases by Postgres ts_rank_cd
        against `query`, using the same plain-text query parsing (plainto_tsquery)
        as a typical keyword search box."""
        if settings.LEXICAL_BACKEND == "bm25":
            return await self._bm25_search(kb_ids, query, top_k)

        kb_uuids = []
        for kb_id in kb_ids:
            try:
                kb_uuids.append(uuid.UUID(kb_id))
            except ValueError:
                continue  # matches vector_store.search_sync's per-KB tolerance
        if not kb_uuids:
            return []

        terms = query_terms(query)
        if not terms:
            return []
        tsquery = reduce(
            lambda a, b: a.op("||")(b),
            [func.plainto_tsquery("simple", term) for term in terms],
        )
        # Base lexical score
        rank_expr = func.ts_rank_cd(KBChunk.content_tsv, tsquery)

        # Give an additional score to phrases explicitly quoted by the user.
        quoted_phrases = [
            next(value for value in groups if value).strip()
            for groups in re.findall(
                r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"",
                query,
            )
        ]

        for phrase in quoted_phrases:
            phrase_tsquery = func.phraseto_tsquery("simple", phrase)
            rank_expr = rank_expr + case(
                (
                    KBChunk.content_tsv.op("@@")(phrase_tsquery),
                    settings.LEXICAL_PHRASE_BOOST,
                ),
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
                "source": "lexical",
            }
            for chunk, score in result.all()
        ]


    async def _bm25_search(self, kb_ids: list[str], query: str, top_k: int,) -> list[dict]:
        """Experimental BM25 retrieval over chunks in selected knowledge bases."""
        if top_k <= 0:
            return []

        kb_uuids = []
        for kb_id in kb_ids:
            try:
                kb_uuids.append(uuid.UUID(kb_id))
            except ValueError:
                continue

        if not kb_uuids:
            return []

        query_tokens = bm25_tokens(query)
        if not query_tokens:
            return []

        stmt = (
            select(KBChunk)
            .where(KBChunk.knowledge_base_id.in_(kb_uuids))
            .order_by(
                KBChunk.knowledge_base_id,
                KBChunk.order_index,
                KBChunk.chunk_id,
            )
        )
        result = await self.db.execute(stmt)
        chunks = list(result.scalars().all())

        # Exclude empty documents before constructing the BM25 index.
        indexed_chunks = []
        tokenized_corpus = []

        for chunk in chunks:
            tokens = bm25_tokens(chunk.content)
            if tokens:
                indexed_chunks.append(chunk)
                tokenized_corpus.append(tokens)

        if not tokenized_corpus:
            return []

        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(query_tokens)

        # Extract explicitly quoted phrases from the query.
        quoted_phrases = [
            next(value for value in groups if value).strip()
            for groups in re.findall(
                r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"",
                query,
            )
        ]

        phrase_token_sequences = [
            bm25_tokens(phrase)
            for phrase in quoted_phrases
        ]
        phrase_token_sequences = [
            tokens for tokens in phrase_token_sequences if tokens
        ]


        def contains_phrase(document_tokens: list[str], phrase_tokens: list[str]) -> bool:
            """Check whether a normalized phrase occurs contiguously."""
            width = len(phrase_tokens)
            return width > 0 and any(
                document_tokens[i:i + width] == phrase_tokens
                for i in range(len(document_tokens) - width + 1)
            )


        query_token_set = set(query_tokens)
        scored_indices = []

        for index, score in enumerate(scores):
            document_tokens = tokenized_corpus[index]
            if not query_token_set.intersection(document_tokens):
                continue

            matched_phrases = sum(
                contains_phrase(document_tokens, phrase_tokens)
                for phrase_tokens in phrase_token_sequences
            )
            scored_indices.append(
                (index, matched_phrases, float(score))
            )

        scored_indices.sort(key=lambda item: (item[1], item[2]), reverse=True)

        hits = []
        for index, _, score in scored_indices[:top_k]:
            chunk = indexed_chunks[index]
            hits.append(
                {
                    "score": score,
                    "chunk_id": str(chunk.chunk_id),
                    "file_id": str(chunk.file_id),
                    "knowledge_base_id": str(chunk.knowledge_base_id),
                    "content": chunk.content,
                    "type": chunk.type,
                    "source": "lexical",
                }
            )

        return hits
