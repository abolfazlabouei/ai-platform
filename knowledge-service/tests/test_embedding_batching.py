"""Smoke test for embedding_service's batching logic, using a stub embedder so no
real API call/key is required."""
from unittest.mock import patch

from app.services.embedding_service import embed_texts_sync


def test_embed_texts_sync_batches_correctly():
    calls = []

    def fake_embed_batch(texts):
        calls.append(list(texts))
        return [[0.0] * 3 for _ in texts]

    with patch("app.services.embedding_service._embed_batch_sync", side_effect=fake_embed_batch):
        with patch("app.core.config.settings.EMBEDDING_BATCH_SIZE", 2):
            # NOTE: patching the imported `settings` object's attribute directly
            # affects the module-level `settings` used inside embed_texts_sync
            # because both reference the same singleton instance.
            vectors = embed_texts_sync(["a", "b", "c", "d", "e"])

    assert len(vectors) == 5
    assert len(calls) == 3  # batches of 2, 2, 1
    assert calls[0] == ["a", "b"]
    assert calls[-1] == ["e"]
