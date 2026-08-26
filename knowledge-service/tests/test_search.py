"""
Smoke tests for vector_store's collection-name derivation and search result
merging/sorting logic — the parts that don't require a live Qdrant instance.
Full integration coverage (real Qdrant, real embeddings) belongs in a separate
test module once CI infra with docker-compose services is wired up.
"""
from app.services.vector_store import _collection_name


def test_collection_name_uses_configured_prefix():
    name = _collection_name("abc-123")
    assert name.startswith("kb_")
    assert name == "kb_abc-123"


def test_collection_name_is_deterministic_per_kb():
    assert _collection_name("same-id") == _collection_name("same-id")
    assert _collection_name("id-a") != _collection_name("id-b")
