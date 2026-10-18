"""
Reciprocal Rank Fusion: merges the dense (Qdrant) and lexical (Postgres
full-text) ranked result lists into one ranking, without needing their raw
scores to be comparable — cosine similarity and ts_rank_cd live on completely
different scales, so RRF works off rank position instead.

RRF(doc) = sum over rankings of 1 / (k + rank_in_ranking)

k=60 is the standard smoothing constant (higher k flattens how much weight a
top rank gets relative to lower ranks).
"""
from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60, weights: list[float] | None = None) -> list[tuple[str, float]]:
    """Weighted Reciprocal Rank Fusion."""
    if weights is None:
        weights = [1.0] * len(rankings)

    if len(weights) != len(rankings):
        raise ValueError("weights and rankings must have the same length")

    scores: dict[str, float] = {}

    for weight, ranking in zip(weights, rankings):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = (
                scores.get(doc_id, 0.0)
                + weight / (k + rank)
            )

    return sorted(scores.items(), key=lambda item: -item[1])
