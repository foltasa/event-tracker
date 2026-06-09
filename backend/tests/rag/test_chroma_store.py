from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.rag import chroma_store


@pytest.fixture
def ephemeral_store(tmp_path, monkeypatch):
    monkeypatch.setattr(chroma_store, "_collection", None)
    monkeypatch.setattr("app.rag.chroma_store.settings.chroma_path", str(tmp_path / "chroma"))
    yield


@patch("app.rag.chroma_store.embed_texts")
def test_upsert_and_query_roundtrip(mock_embed, ephemeral_store):
    mock_embed.side_effect = lambda texts: [[0.1 * (i + 1)] * 1536 for i in range(len(texts))]

    chroma_store.upsert_events([
        chroma_store.EventForEmbedding(
            id="e1", title="Jazz Night", description="Trio at Mojo",
            category="music", venue_name="Mojo", neighborhood="St. Pauli",
            start_datetime=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc),
        ),
        chroma_store.EventForEmbedding(
            id="e2", title="Hackathon", description="48-hour build sprint",
            category="tech", venue_name="Betahaus", neighborhood="Schanzenviertel",
            start_datetime=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        ),
    ])

    hits = chroma_store.query_by_vector([0.1] * 1536, n=2)
    assert len(hits) == 2
    assert {h.event_id for h in hits} == {"e1", "e2"}


@patch("app.rag.chroma_store.embed_texts")
def test_query_with_category_filter(mock_embed, ephemeral_store):
    mock_embed.side_effect = lambda texts: [[0.1] * 1536 for _ in texts]
    chroma_store.upsert_events([
        chroma_store.EventForEmbedding(
            id="m1", title="Concert", description="", category="music",
            venue_name=None, neighborhood=None,
            start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
        ),
        chroma_store.EventForEmbedding(
            id="t1", title="Talk", description="", category="tech",
            venue_name=None, neighborhood=None,
            start_datetime=datetime(2026, 6, 11, tzinfo=timezone.utc),
        ),
    ])

    hits = chroma_store.query_by_vector(
        [0.1] * 1536, n=10, where={"category": {"$in": ["tech"]}},
    )
    assert [h.event_id for h in hits] == ["t1"]


@patch("app.rag.chroma_store.embed_texts")
def test_get_embeddings_for_ids(mock_embed, ephemeral_store):
    mock_embed.side_effect = lambda texts: [[float(i)] * 1536 for i, _ in enumerate(texts)]
    chroma_store.upsert_events([
        chroma_store.EventForEmbedding(
            id="a", title="A", description="", category="music",
            venue_name=None, neighborhood=None,
            start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
        ),
    ])

    embs = chroma_store.get_embeddings_for_ids(["a", "missing"])
    assert set(embs.keys()) == {"a"}
    assert len(embs["a"]) == 1536


def test_query_with_no_collection_returns_empty(ephemeral_store):
    assert chroma_store.query_by_vector([0.1] * 1536, n=5) == []
