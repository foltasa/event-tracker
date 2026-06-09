"""Chroma vector store for events. Single collection; agent and ingestion both use it."""
from dataclasses import dataclass
from datetime import datetime

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.rag.embeddings import embed_texts

_collection = None
COLLECTION_NAME = "events"


@dataclass
class EventForEmbedding:
    id: str
    title: str
    description: str | None
    category: str
    venue_name: str | None
    neighborhood: str | None
    start_datetime: datetime


@dataclass
class QueryHit:
    event_id: str
    similarity_score: float


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _format_document(e: EventForEmbedding) -> str:
    parts = [e.title]
    if e.description:
        parts.append("")
        parts.append(e.description)
    parts.append("")
    parts.append(f"Category: {e.category}")
    venue = ", ".join(p for p in [e.venue_name, e.neighborhood] if p)
    if venue:
        parts.append(f"Venue: {venue}")
    return "\n".join(parts)


def upsert_events(events: list[EventForEmbedding]) -> None:
    if not events:
        return
    coll = _get_collection()
    documents = [_format_document(e) for e in events]
    vectors = embed_texts(documents)
    coll.upsert(
        ids=[e.id for e in events],
        embeddings=vectors,
        documents=documents,
        metadatas=[
            {
                "category": e.category,
                "start_time": int(e.start_datetime.timestamp()),
            }
            for e in events
        ],
    )


def query_by_vector(
    vector: list[float],
    n: int,
    where: dict | None = None,
) -> list[QueryHit]:
    coll = _get_collection()
    if coll.count() == 0:
        return []
    result = coll.query(
        query_embeddings=[vector],
        n_results=min(n, coll.count()),
        where=where,
    )
    ids = result["ids"][0]
    distances = result["distances"][0]
    return [QueryHit(event_id=i, similarity_score=1.0 - d) for i, d in zip(ids, distances)]


def get_embeddings_for_ids(event_ids: list[str]) -> dict[str, list[float]]:
    coll = _get_collection()
    if not event_ids or coll.count() == 0:
        return {}
    result = coll.get(ids=event_ids, include=["embeddings"])
    return dict(zip(result["ids"], result["embeddings"]))
