# Agent Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LangGraph-based agent, its 7 function tools, the memory layer (chat checkpointer + chat_messages mirror + users-row taste summary/centroid), the RAG layer over Chroma, and the 6 FastAPI route modules that expose them.

**Architecture:** A single LangGraph prebuilt `create_react_agent` runs both curation and conversational modes — they differ only in system prompt, `response_format`, and `thread_id` scheme. Tools are thin wrappers over DB session helpers and a Chroma-backed RAG layer. Short-term chat history uses LangGraph's `SqliteSaver`; long-term taste lives on the `users` row (summary + centroid + dirty flag).

**Tech Stack:** Python 3.11, FastAPI, LangGraph (`langgraph`, `langchain-openai`), Chroma (`chromadb`), OpenAI Python SDK (for embeddings, via OpenRouter for chat), SQLAlchemy, Alembic, pytest.

**Source-of-truth schemas:** Use the existing Pydantic models in `backend/app/schemas/` (merged in PR #2). Where the brainstorm spec sketched alternative names (`sentiment='up'`, bare-`event_id` digest picks, custom SSE event types), the existing schemas win because the frontend already consumes them.

---

## File Structure

**New files (in `backend/`):**

```
app/
  agent/
    __init__.py
    llm.py            # build_llm() — ChatOpenAI -> OpenRouter
    memory.py         # contextvar, record_message, summary/centroid helpers
    prompts.py        # CURATION_PROMPT, CONVERSATIONAL_PROMPT, SUMMARY_PROMPT
    runtime.py        # build_agent() — wires LLM + tools + checkpointer
    schemas.py        # internal LLM-facing models (LLMDigestPick, etc.) + ToolError
    tools.py          # 7 @tool functions
  rag/
    __init__.py
    embeddings.py     # OpenAIEmbeddings client wrapper
    chroma_store.py   # collection mgmt, upsert/query/get_by_ids
  api/
    __init__.py
    deps.py           # X-User-Id middleware + contextvar setter
    routes_calendar.py
    routes_chat.py
    routes_digest.py
    routes_events.py
    routes_feedback.py
    routes_profile.py
  db/migrations/versions/0002_user_taste_fields.py
data/                  # gitignored, holds agent.sqlite (LangGraph checkpointer)
tests/
  agent/
    __init__.py
    conftest.py       # FakeLLM helper
    test_llm.py
    test_memory.py
    test_prompts.py
    test_runtime.py
    test_tools.py
  rag/
    __init__.py
    test_chroma_store.py
    test_embeddings.py
  api/
    test_routes_calendar.py
    test_routes_chat.py
    test_routes_digest.py
    test_routes_events.py
    test_routes_feedback.py
    test_routes_profile.py
  integration/
    __init__.py
    test_chat_sse.py
    test_digest_cycle.py
```

**Modified files:**

- `backend/pyproject.toml` — add deps.
- `backend/app/config.py` — add LLM/RAG settings.
- `backend/app/db/models/user.py` — two new columns.
- `backend/app/main.py` — register routers + X-User-Id middleware.
- `backend/app/ingestion/scheduler.py` — wire `embed_new_events` to chroma_store.
- `backend/tests/conftest.py` — add `client` and `agent_app` fixtures.
- `backend/.gitignore` — add `data/`.

---

## Task 1: Add dependencies and config

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/.gitignore` (create if absent)
- Create: `backend/data/.gitkeep`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_config.py`:

```python
from app.config import settings


def test_agent_settings_have_defaults():
    assert settings.agent_model == "openai/gpt-4o-mini"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.chroma_path == "./data/chroma"
    assert settings.checkpointer_path == "./data/agent.sqlite"


def test_agent_settings_optional_keys():
    assert hasattr(settings, "openrouter_api_key")
    assert hasattr(settings, "openai_api_key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: agent_model`.

- [ ] **Step 3: Add dependencies to `backend/pyproject.toml`**

Replace the `dependencies = [...]` block with:

```toml
dependencies = [
    "sqlalchemy>=2.0.30",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.2.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.3",
    "apscheduler>=3.10.4,<4",
    "pytz>=2024.1",
    "tzdata>=2024.1",
    "langgraph>=0.2.45",
    "langgraph-checkpoint-sqlite>=2.0.0",
    "langchain-openai>=0.2.0",
    "langchain-core>=0.3.0",
    "chromadb>=0.5.0",
    "openai>=1.40.0",
    "numpy>=1.26.0",
    "sse-starlette>=2.1.0",
]
```

- [ ] **Step 4: Update `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    # Agent / LLM
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None  # used by embeddings (OpenAI direct, not via OpenRouter)
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7
    summary_model: str = "openai/gpt-4o-mini"

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    # LangGraph checkpointer
    checkpointer_path: str = "./data/agent.sqlite"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
```

- [ ] **Step 5: Create gitignored data dir**

Create `backend/.gitignore` (or append if present):

```gitignore
data/
*.db
__pycache__/
.pytest_cache/
```

Create `backend/data/.gitkeep` as an empty file so the dir is committed but its contents are ignored.

- [ ] **Step 6: Install deps and run test**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/.gitignore backend/data/.gitkeep backend/tests/test_config.py
git commit -m "chore: add agent/RAG dependencies and config settings"
```

---

## Task 2: Migrate `users` table for taste fields

**Files:**
- Modify: `backend/app/db/models/user.py`
- Create: `backend/app/db/migrations/versions/0002_user_taste_fields.py`
- Modify: `backend/tests/db/test_user.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/db/test_user.py`:

```python
def test_user_has_taste_centroid_and_dirty_flag(db_session):
    from app.db.models import User
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    fresh = db_session.query(User).filter_by(id="local").first()
    assert fresh.taste_summary_dirty is True  # default true => first read triggers initial summary
    assert fresh.taste_centroid is None


def test_user_taste_centroid_roundtrip(db_session):
    from app.db.models import User
    u = User(id="local", interest_tags=[], taste_centroid=[0.1, 0.2, 0.3])
    db_session.add(u)
    db_session.commit()
    fresh = db_session.query(User).filter_by(id="local").first()
    assert fresh.taste_centroid == [0.1, 0.2, 0.3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/db/test_user.py -v`
Expected: FAIL — `taste_summary_dirty` / `taste_centroid` attributes don't exist.

- [ ] **Step 3: Update the User model**

Replace `backend/app/db/models/user.py` body with:

```python
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, nullable=False, default="Hamburg")
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    about_me: Mapped[str | None] = mapped_column(String, nullable=True)
    taste_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    taste_summary_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    taste_centroid: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
```

(`taste_centroid` stored as JSON `list[float]` rather than packed bytes — simpler, ~20 KB per user, still trivial for an MVP.)

- [ ] **Step 4: Create Alembic migration**

Create `backend/app/db/migrations/versions/0002_user_taste_fields.py`:

```python
"""user taste fields

Revision ID: 0002_user_taste_fields
Revises: 0001_initial
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_user_taste_fields"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_summary_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("taste_centroid", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "taste_centroid")
    op.drop_column("users", "taste_summary_dirty")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/db/test_user.py -v`
Expected: PASS for all user tests including the two new ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/user.py backend/app/db/migrations/versions/0002_user_taste_fields.py backend/tests/db/test_user.py
git commit -m "feat(db): add taste_summary_dirty and taste_centroid to users"
```

---

## Task 3: RAG — embeddings client

**Files:**
- Create: `backend/app/rag/__init__.py` (empty)
- Create: `backend/app/rag/embeddings.py`
- Create: `backend/tests/rag/__init__.py` (empty)
- Create: `backend/tests/rag/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/rag/test_embeddings.py`:

```python
from unittest.mock import MagicMock, patch

from app.rag.embeddings import embed_texts


@patch("app.rag.embeddings._client")
def test_embed_texts_returns_one_vector_per_input(mock_client):
    mock_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536), MagicMock(embedding=[0.2] * 1536)],
    )

    vectors = embed_texts(["hello", "world"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 1536
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input=["hello", "world"],
    )


@patch("app.rag.embeddings._client")
def test_embed_texts_empty_returns_empty(mock_client):
    assert embed_texts([]) == []
    mock_client.embeddings.create.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/rag/test_embeddings.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement embeddings**

`backend/app/rag/embeddings.py`:

```python
"""OpenAI embeddings client. Uses OpenAI directly (not via OpenRouter) for
embeddings — OpenRouter does not proxy text-embedding-3-small."""
from openai import OpenAI

from app.config import settings

_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else OpenAI()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = _client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in resp.data]


def embed_one(text: str) -> list[float]:
    vectors = embed_texts([text])
    return vectors[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/rag/test_embeddings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/__init__.py backend/app/rag/embeddings.py backend/tests/rag/__init__.py backend/tests/rag/test_embeddings.py
git commit -m "feat(rag): add OpenAI embeddings client wrapper"
```

---

## Task 4: RAG — Chroma store

**Files:**
- Create: `backend/app/rag/chroma_store.py`
- Create: `backend/tests/rag/test_chroma_store.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/rag/test_chroma_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/rag/test_chroma_store.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement chroma_store**

`backend/app/rag/chroma_store.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/rag/test_chroma_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/chroma_store.py backend/tests/rag/test_chroma_store.py
git commit -m "feat(rag): add Chroma store with upsert/query/get_embeddings"
```

---

## Task 5: Wire ingestion embed_new_events to Chroma

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py` (add a test, do not break existing)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
def test_embed_new_events_upserts_active_events_to_chroma(monkeypatch, db_session):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from app.db.models import Event
    from app.ingestion import scheduler

    db_session.add(Event(
        id="e1", external_id="ext1", source="eventbrite", title="Jazz",
        description="d", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
        is_active=True,
    ))
    db_session.add(Event(
        id="e2", external_id="ext2", source="eventbrite", title="Old",
        description="d", category="music", source_url="http://x",
        start_datetime=datetime(2020, 1, 1, tzinfo=timezone.utc),
        is_active=False,
    ))
    db_session.commit()

    fake_upsert = MagicMock()
    monkeypatch.setattr("app.ingestion.scheduler.chroma_upsert_events", fake_upsert)

    scheduler.embed_new_events(db_session)

    fake_upsert.assert_called_once()
    payload = fake_upsert.call_args.args[0]
    assert len(payload) == 1
    assert payload[0].id == "e1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/ingestion/test_scheduler.py::test_embed_new_events_upserts_active_events_to_chroma -v`
Expected: FAIL — current `embed_new_events` is a no-op stub.

- [ ] **Step 3: Implement embedding wire-up**

In `backend/app/ingestion/scheduler.py`, replace the `embed_new_events` stub with:

```python
from app.db.models import Event
from app.rag.chroma_store import EventForEmbedding
from app.rag.chroma_store import upsert_events as chroma_upsert_events


def embed_new_events(session: Session) -> None:
    """Embed all currently-active events into Chroma. Idempotent: upsert by id."""
    rows = session.query(Event).filter(Event.is_active == True).all()  # noqa: E712
    if not rows:
        logger.info("embed_new_events: no active events")
        return
    payload = [
        EventForEmbedding(
            id=r.id,
            title=r.title,
            description=r.description,
            category=r.category,
            venue_name=r.venue_name,
            neighborhood=None,  # not in the current schema; leave None for MVP
            start_datetime=r.start_datetime,
        )
        for r in rows
    ]
    chroma_upsert_events(payload)
    logger.info("embed_new_events: embedded %d events", len(payload))
```

(Keep the existing imports at the top of the file; add the three new imports listed above.)

- [ ] **Step 4: Run tests to verify pass and nothing else broke**

Run: `cd backend && pytest tests/ingestion/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(ingestion): embed active events into Chroma after upsert"
```

---

## Task 6: Agent internal schemas + ToolError

**Files:**
- Create: `backend/app/agent/__init__.py` (empty)
- Create: `backend/app/agent/schemas.py`
- Create: `backend/tests/agent/__init__.py` (empty)
- Create: `backend/tests/agent/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/agent/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.agent.schemas import EventSummary, LLMDigestPick, LLMDigestResponse, ToolError


def test_llm_digest_response_enforces_3_to_5_picks():
    too_few = [LLMDigestPick(event_id=str(i), justification="j") for i in range(2)]
    with pytest.raises(ValidationError):
        LLMDigestResponse(picks=too_few)

    too_many = [LLMDigestPick(event_id=str(i), justification="j") for i in range(6)]
    with pytest.raises(ValidationError):
        LLMDigestResponse(picks=too_many)

    just_right = [LLMDigestPick(event_id=str(i), justification="j") for i in range(4)]
    LLMDigestResponse(picks=just_right)


def test_event_summary_fields():
    s = EventSummary(
        id="e1", title="t", category="music",
        start_datetime="2026-06-10T20:00:00Z", venue_name="Mojo",
        is_free=False, source_url="http://x",
    )
    assert s.id == "e1"


def test_tool_error_is_exception():
    err = ToolError("nope")
    assert isinstance(err, Exception)
    assert str(err) == "nope"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_schemas.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement schemas**

`backend/app/agent/schemas.py`:

```python
"""Internal models used by the agent layer (tools, structured outputs).
NOT to be confused with `app/schemas/`, which are API contract models."""
from datetime import datetime

from pydantic import BaseModel, Field


class ToolError(Exception):
    """Raised by tool functions on user-facing failures.
    The prebuilt LangGraph agent catches and forwards the message to the LLM."""


class EventSummary(BaseModel):
    """Compact event shape returned by read tools."""
    id: str
    title: str
    category: str
    start_datetime: datetime
    venue_name: str | None = None
    is_free: bool = False
    price_min: float | None = None
    source_url: str
    similarity_score: float | None = None


class LLMDigestPick(BaseModel):
    event_id: str
    justification: str = Field(min_length=10)


class LLMDigestResponse(BaseModel):
    picks: list[LLMDigestPick] = Field(min_length=3, max_length=5)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/__init__.py backend/app/agent/schemas.py backend/tests/agent/__init__.py backend/tests/agent/test_schemas.py
git commit -m "feat(agent): add internal schemas (EventSummary, LLMDigestResponse, ToolError)"
```

---

## Task 7: LLM client builder

**Files:**
- Create: `backend/app/agent/llm.py`
- Create: `backend/tests/agent/test_llm.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/agent/test_llm.py`:

```python
from unittest.mock import patch

from app.agent.llm import build_llm


@patch("app.agent.llm.ChatOpenAI")
def test_build_llm_targets_openrouter(mock_chat):
    build_llm()
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["streaming"] is True


@patch("app.agent.llm.ChatOpenAI")
def test_build_llm_accepts_overrides(mock_chat):
    build_llm(model="anthropic/claude-haiku-4.5", temperature=0.2)
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["model"] == "anthropic/claude-haiku-4.5"
    assert kwargs["temperature"] == 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/agent/test_llm.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement build_llm**

`backend/app/agent/llm.py`:

```python
"""ChatOpenAI client pointed at OpenRouter. Single provider for MVP;
multi-model UI plugs in here later."""
from langchain_openai import ChatOpenAI

from app.config import settings


def build_llm(model: str | None = None, temperature: float | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.agent_model,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature if temperature is not None else settings.agent_temperature,
        streaming=True,
    ).with_retry(stop_after_attempt=2, wait_exponential_jitter=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_llm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/llm.py backend/tests/agent/test_llm.py
git commit -m "feat(agent): add LLM client builder targeting OpenRouter"
```

---

## Task 8: Memory helpers — contextvar, record_message, taste centroid/summary

**Files:**
- Create: `backend/app/agent/memory.py`
- Create: `backend/tests/agent/conftest.py`
- Create: `backend/tests/agent/test_memory.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/agent/conftest.py`:

```python
"""Shared fixtures for agent tests."""
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeMessage:
    content: str


@dataclass
class FakeLLM:
    """Minimal stand-in that records calls and returns scripted responses."""
    responses: list[str] = field(default_factory=list)
    calls: list[list] = field(default_factory=list)

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        text = self.responses.pop(0) if self.responses else "ok"
        return FakeMessage(content=text)


@pytest.fixture
def fake_llm():
    return FakeLLM()
```

`backend/tests/agent/test_memory.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.agent import memory
from app.db.models import ChatMessage, Event, Feedback, User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    return u


def test_user_id_contextvar_get_default(monkeypatch):
    monkeypatch.setattr("app.agent.memory.settings.default_user_id", "local")
    memory._current_user_id.set(None)
    assert memory.get_current_user_id() == "local"


def test_user_id_contextvar_set_and_get():
    memory._current_user_id.set("alice")
    try:
        assert memory.get_current_user_id() == "alice"
    finally:
        memory._current_user_id.set(None)


def test_record_message_writes_row(db_session, user):
    memory.record_message(
        session=db_session,
        session_id="s1",
        user_id="local",
        role="user",
        content="hi",
    )
    db_session.commit()
    rows = db_session.query(ChatMessage).filter_by(session_id="s1").all()
    assert len(rows) == 1
    assert rows[0].role == "user"
    assert rows[0].content == "hi"


def test_refresh_taste_summary_skips_when_clean(db_session, user):
    user.taste_summary_dirty = False
    user.taste_summary = "existing"
    db_session.commit()
    with patch("app.agent.memory._invoke_summary_llm") as mock_llm:
        result = memory.refresh_taste_summary(db_session, "local")
    assert result == "existing"
    mock_llm.assert_not_called()


def test_refresh_taste_summary_regenerates_when_dirty(db_session, user):
    user.taste_summary_dirty = True
    db_session.commit()
    with patch("app.agent.memory._invoke_summary_llm", return_value="loves jazz"):
        result = memory.refresh_taste_summary(db_session, "local")
    assert result == "loves jazz"
    db_session.refresh(user)
    assert user.taste_summary == "loves jazz"
    assert user.taste_summary_dirty is False


def test_refresh_taste_centroid_no_likes_sets_null(db_session, user):
    memory.refresh_taste_centroid(db_session, "local")
    db_session.refresh(user)
    assert user.taste_centroid is None


def test_refresh_taste_centroid_averages_liked_embeddings(db_session, user):
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite", title="t",
        category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.add(Feedback(id="f1", user_id="local", event_id="e1", sentiment="like"))
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e1": [0.5] * 1536},
    ):
        memory.refresh_taste_centroid(db_session, "local")

    db_session.refresh(user)
    assert user.taste_centroid is not None
    assert len(user.taste_centroid) == 1536
    assert user.taste_centroid[0] == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_memory.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement memory helpers**

`backend/app/agent/memory.py`:

```python
"""Memory helpers shared by the agent runtime and routes.

- ContextVar for per-request user_id (set by middleware, read by tools).
- record_message: append a row to chat_messages mirror.
- refresh_taste_summary: lazy regen when users.taste_summary_dirty.
- refresh_taste_centroid: recompute from 'like' feedback embeddings.
"""
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.agent.llm import build_llm
from app.agent.prompts import SUMMARY_PROMPT
from app.config import settings
from app.db.models import ChatMessage, Feedback, SavedEvent, User
from app.rag.chroma_store import get_embeddings_for_ids

logger = logging.getLogger(__name__)

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> str:
    return _current_user_id.get() or settings.default_user_id


def set_current_user_id(user_id: str | None) -> None:
    _current_user_id.set(user_id)


def record_message(
    session: Session,
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        tool_name=tool_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        created_at=datetime.now(timezone.utc),
    )
    session.add(msg)
    return msg


def _invoke_summary_llm(prompt: str) -> str:
    llm = build_llm(model=settings.summary_model, temperature=0.3)
    return llm.invoke(prompt).content


def refresh_taste_summary(session: Session, user_id: str) -> str | None:
    user = session.query(User).filter_by(id=user_id).one()
    if not user.taste_summary_dirty:
        return user.taste_summary

    recent_feedback = (
        session.query(Feedback)
        .filter_by(user_id=user_id)
        .order_by(Feedback.created_at.desc())
        .limit(30)
        .all()
    )
    recent_saved = (
        session.query(SavedEvent)
        .filter_by(user_id=user_id)
        .order_by(SavedEvent.saved_at.desc())
        .limit(10)
        .all()
    )

    feedback_lines = [
        f"- {f.sentiment} (event {f.event_id})" + (f": {f.comment}" if f.comment else "")
        for f in recent_feedback
    ]
    saved_lines = [f"- saved event {s.event_id}" for s in recent_saved]

    prompt = SUMMARY_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        feedback="\n".join(feedback_lines) or "(none yet)",
        saved="\n".join(saved_lines) or "(none yet)",
    )

    try:
        summary = _invoke_summary_llm(prompt).strip()
    except Exception:
        logger.exception("refresh_taste_summary: LLM failed; leaving prior summary")
        return user.taste_summary

    user.taste_summary = summary
    user.taste_summary_dirty = False
    session.flush()
    return summary


def refresh_taste_centroid(session: Session, user_id: str) -> None:
    liked = (
        session.query(Feedback)
        .filter_by(user_id=user_id, sentiment="like")
        .all()
    )
    user = session.query(User).filter_by(id=user_id).one()

    if not liked:
        user.taste_centroid = None
        session.flush()
        return

    embeddings = get_embeddings_for_ids([f.event_id for f in liked])
    if not embeddings:
        user.taste_centroid = None
        session.flush()
        return

    matrix = np.array(list(embeddings.values()), dtype=np.float32)
    centroid = matrix.mean(axis=0).tolist()
    user.taste_centroid = centroid
    session.flush()
```

- [ ] **Step 4: Create stub prompts so the import works**

Create `backend/app/agent/prompts.py` (placeholder content; Task 11 fills in full prompts):

```python
"""Agent prompt templates.

Tasks 11 fills these in fully. The Summary prompt is needed for memory.py
imports at Task 8, so it is defined here from the start."""

SUMMARY_PROMPT = """\
You are summarising a user's event taste based on their reactions.

Interests (stated): {interests}
About-me: {about_me}

Recent feedback (newest first):
{feedback}

Recently saved:
{saved}

Write a single paragraph of at most 80 words capturing the user's taste —
what they consistently like, what they dislike, and any patterns
(venue type, vibe, day of week). Use natural language. No lists.
"""

CURATION_PROMPT = "PLACEHOLDER — replaced in Task 11"
CONVERSATIONAL_PROMPT = "PLACEHOLDER — replaced in Task 11"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_memory.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/memory.py backend/app/agent/prompts.py backend/tests/agent/conftest.py backend/tests/agent/test_memory.py
git commit -m "feat(agent): add memory helpers (contextvar, record_message, taste refresh)"
```

---

## Task 9: Tools — read-only (search_events, get_calendar)

**Files:**
- Create: `backend/app/agent/tools.py`
- Create: `backend/tests/agent/test_tools.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/agent/test_tools.py`:

```python
from datetime import datetime, timezone

import pytest

from app.agent.schemas import ToolError
from app.agent import tools
from app.db.models import Event, SavedEvent, User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def events(db_session, user):
    rows = [
        Event(
            id="e_music", external_id="m1", source="eventbrite",
            title="Jazz Night", description="Trio at Mojo",
            category="music", source_url="http://x",
            start_datetime=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc),
            venue_name="Mojo", is_free=False, price_min=10.0,
        ),
        Event(
            id="e_tech", external_id="t1", source="eventbrite",
            title="Python Meetup", description="Talks",
            category="tech", source_url="http://x",
            start_datetime=datetime(2026, 6, 12, 19, 0, tzinfo=timezone.utc),
            venue_name="Betahaus", is_free=True,
        ),
    ]
    for r in rows:
        db_session.add(r)
    db_session.commit()
    return rows


def test_search_events_by_category(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke({"categories": ["music"]})
    assert len(results) == 1
    assert results[0]["id"] == "e_music"


def test_search_events_by_text(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke({"text": "python"})
    assert {r["id"] for r in results} == {"e_tech"}


def test_search_events_date_range(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke(
        {"date_from": "2026-06-11", "date_to": "2026-06-13"}
    )
    assert {r["id"] for r in results} == {"e_tech"}


def test_get_calendar_empty(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    assert tools.get_calendar.invoke({}) == []


def test_get_calendar_returns_saved(db_session, events, monkeypatch):
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="e_music"))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    results = tools.get_calendar.invoke({})
    assert [r["id"] for r in results] == ["e_music"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement read-only tools**

`backend/app/agent/tools.py`:

```python
"""LangChain tools the agent calls. Each is a thin wrapper over the DB / RAG.

Tools resolve user_id via the agent.memory contextvar. They open and close
their own DB session so the agent layer does not need to thread sessions
through tool signatures.
"""
import logging
from datetime import date, datetime, time, timezone

import numpy as np
from langchain_core.tools import tool
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.agent.memory import get_current_user_id
from app.agent.schemas import ToolError
from app.db.models import Event, Feedback, SavedEvent, User
from app.db.session import SessionLocal
from app.rag import chroma_store
from app.rag.embeddings import embed_one

logger = logging.getLogger(__name__)


def _session_factory() -> Session:
    return SessionLocal()


def _event_to_summary(e: Event, similarity_score: float | None = None) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "category": e.category,
        "start_datetime": e.start_datetime.isoformat(),
        "venue_name": e.venue_name,
        "is_free": e.is_free,
        "price_min": e.price_min,
        "source_url": e.source_url,
        "similarity_score": similarity_score,
    }


@tool
def search_events(
    date_from: str | None = None,
    date_to: str | None = None,
    categories: list[str] | None = None,
    text: str | None = None,
    max_price: float | None = None,
    location: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search the events catalogue.

    Args:
        date_from: ISO date (YYYY-MM-DD), inclusive lower bound on start_datetime.
        date_to: ISO date (YYYY-MM-DD), inclusive upper bound on start_datetime.
        categories: limit to these category strings (e.g. ["music", "tech"]).
        text: case-insensitive substring match on title or description.
        max_price: include only events whose price_min is <= this (or is_free=True).
        location: case-insensitive substring match on venue_name.
        limit: max rows returned (default 20, hard cap 50).
    """
    session = _session_factory()
    try:
        q = session.query(Event).filter(Event.is_active == True)  # noqa: E712
        if date_from:
            q = q.filter(Event.start_datetime >= datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
        if date_to:
            q = q.filter(Event.start_datetime <= datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))
        if categories:
            q = q.filter(Event.category.in_(categories))
        if text:
            like = f"%{text.lower()}%"
            q = q.filter(or_(Event.title.ilike(like), Event.description.ilike(like)))
        if max_price is not None:
            q = q.filter(or_(Event.is_free == True, Event.price_min <= max_price))  # noqa: E712
        if location:
            q = q.filter(Event.venue_name.ilike(f"%{location}%"))

        rows = q.order_by(Event.start_datetime.asc()).limit(min(limit, 50)).all()
        return [_event_to_summary(r) for r in rows]
    finally:
        session.close()


@tool
def get_calendar(date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Return events the current user has saved to their calendar.

    Args:
        date_from: ISO date filter on start_datetime, inclusive.
        date_to: ISO date filter on start_datetime, inclusive.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        q = (
            session.query(Event)
            .join(SavedEvent, SavedEvent.event_id == Event.id)
            .filter(SavedEvent.user_id == user_id)
        )
        if date_from:
            q = q.filter(Event.start_datetime >= datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
        if date_to:
            q = q.filter(Event.start_datetime <= datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))
        rows = q.order_by(Event.start_datetime.asc()).all()
        return [_event_to_summary(r) for r in rows]
    finally:
        session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: PASS for the 5 read-only-tool tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/agent/test_tools.py
git commit -m "feat(agent): add read-only tools (search_events, get_calendar)"
```

---

## Task 10: Tools — writes (save_to_calendar, get_user_profile, update_user_profile)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/tests/agent/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/agent/test_tools.py`:

```python
def test_save_to_calendar_idempotent(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    tools.save_to_calendar.invoke({"event_id": "e_music"})
    tools.save_to_calendar.invoke({"event_id": "e_music"})  # second call must not raise
    rows = db_session.query(SavedEvent).filter_by(user_id="local", event_id="e_music").all()
    assert len(rows) == 1


def test_save_to_calendar_unknown_raises_toolerror(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    with pytest.raises(ToolError, match="event not found"):
        tools.save_to_calendar.invoke({"event_id": "nope"})


def test_get_user_profile_returns_profile(db_session, user, monkeypatch):
    user.taste_summary_dirty = False
    user.taste_summary = "loves jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    result = tools.get_user_profile.invoke({})
    assert result == {
        "interest_tags": ["music"],
        "about_me": None,
        "taste_summary": "loves jazz",
    }


def test_update_user_profile_marks_dirty(db_session, user, monkeypatch):
    user.taste_summary_dirty = False
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    tools.update_user_profile.invoke({"interest_tags": ["music", "tech"], "about_me": "loves indie"})
    db_session.refresh(user)
    assert user.interest_tags == ["music", "tech"]
    assert user.about_me == "loves indie"
    assert user.taste_summary_dirty is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: 4 new tests FAIL (tools not yet defined).

- [ ] **Step 3: Implement the write tools**

Append to `backend/app/agent/tools.py`:

```python
@tool
def save_to_calendar(event_id: str) -> dict:
    """Save an event to the current user's calendar. Idempotent on (user, event)."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        if not session.query(Event).filter_by(id=event_id).first():
            raise ToolError("event not found")
        exists = session.query(SavedEvent).filter_by(user_id=user_id, event_id=event_id).first()
        if exists:
            return {"status": "ok", "already_saved": True}
        import uuid as _uuid
        session.add(SavedEvent(id=str(_uuid.uuid4()), user_id=user_id, event_id=event_id))
        session.commit()
        return {"status": "ok", "already_saved": False}
    finally:
        session.close()


@tool
def get_user_profile() -> dict:
    """Return the current user's interests, about-me, and distilled taste summary."""
    from app.agent.memory import refresh_taste_summary
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        refresh_taste_summary(session, user_id)
        session.commit()
        session.refresh(user)
        return {
            "interest_tags": list(user.interest_tags),
            "about_me": user.about_me,
            "taste_summary": user.taste_summary,
        }
    finally:
        session.close()


@tool
def update_user_profile(
    interest_tags: list[str] | None = None,
    about_me: str | None = None,
) -> dict:
    """Update user profile fields. Any field omitted is left unchanged.
    Marks the taste summary dirty so it regenerates on next read."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        if interest_tags is not None:
            user.interest_tags = interest_tags
        if about_me is not None:
            user.about_me = about_me
        user.taste_summary_dirty = True
        session.commit()
        return {"status": "ok"}
    finally:
        session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/agent/test_tools.py
git commit -m "feat(agent): add profile/calendar write tools"
```

---

## Task 11: Tools — RAG-backed and feedback (get_recommendations, record_feedback)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/tests/agent/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/agent/test_tools.py`:

```python
def test_get_recommendations_cold_start_uses_interest_tags(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "embed_one", lambda text: [0.42] * 1536)

    captured = {}

    def fake_query(vector, n, where=None):
        captured["vector"] = vector
        captured["n"] = n
        return [
            chroma_store.QueryHit(event_id="e_music", similarity_score=0.9),
            chroma_store.QueryHit(event_id="e_tech", similarity_score=0.8),
        ]

    monkeypatch.setattr(tools.chroma_store, "query_by_vector", fake_query)

    results = tools.get_recommendations.invoke({"n": 2})
    assert len(results) == 2
    assert results[0]["id"] == "e_music"
    assert results[0]["similarity_score"] == 0.9
    assert captured["vector"] == [0.42] * 1536


def test_get_recommendations_uses_centroid_when_present(db_session, user, events, monkeypatch):
    user.taste_centroid = [0.7] * 1536
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "embed_one", lambda text: pytest.fail("must not embed when centroid set"))
    captured = {}

    def fake_query(vector, n, where=None):
        captured["vector"] = vector
        return [chroma_store.QueryHit(event_id="e_music", similarity_score=0.99)]

    monkeypatch.setattr(tools.chroma_store, "query_by_vector", fake_query)

    results = tools.get_recommendations.invoke({"n": 1})
    assert captured["vector"] == [0.7] * 1536
    assert results[0]["id"] == "e_music"


def test_record_feedback_inserts_and_marks_dirty(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "refresh_taste_centroid", lambda s, uid: None)

    tools.record_feedback.invoke({
        "event_id": "e_music", "sentiment": "like", "comment": "loved it",
    })

    row = db_session.query(Feedback).filter_by(user_id="local", event_id="e_music").one()
    assert row.sentiment == "like"
    assert row.comment == "loved it"
    user = db_session.query(User).filter_by(id="local").one()
    assert user.taste_summary_dirty is True


def test_record_feedback_like_refreshes_centroid(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    called = {"refreshed": False}

    def fake_refresh(s, uid):
        called["refreshed"] = True

    monkeypatch.setattr(tools, "refresh_taste_centroid", fake_refresh)
    tools.record_feedback.invoke({"event_id": "e_music", "sentiment": "like"})
    assert called["refreshed"] is True


def test_record_feedback_dislike_skips_centroid_refresh(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    called = {"refreshed": False}

    def fake_refresh(s, uid):
        called["refreshed"] = True

    monkeypatch.setattr(tools, "refresh_taste_centroid", fake_refresh)
    tools.record_feedback.invoke({"event_id": "e_music", "sentiment": "dislike"})
    assert called["refreshed"] is False


def test_record_feedback_unknown_event_raises(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    with pytest.raises(ToolError, match="event not found"):
        tools.record_feedback.invoke({"event_id": "nope", "sentiment": "like"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: new tests FAIL (tools not yet defined).

- [ ] **Step 3: Implement the RAG-backed and feedback tools**

Append to `backend/app/agent/tools.py`:

```python
from app.agent.memory import refresh_taste_centroid


@tool
def get_recommendations(
    date_from: str | None = None,
    date_to: str | None = None,
    n: int = 10,
) -> list[dict]:
    """Recommend events ranked by similarity to the user's taste.

    Uses the user's taste centroid (mean of liked-event embeddings) when
    available; otherwise falls back to embedding their interest tags."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")

        if user.taste_centroid is not None and len(user.taste_centroid) > 0:
            vector = list(user.taste_centroid)
        elif user.interest_tags:
            vector = embed_one(", ".join(user.interest_tags))
        else:
            return []

        where = None
        ranges = []
        if date_from:
            ranges.append({"start_time": {"$gte": int(datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc).timestamp())}})
        if date_to:
            ranges.append({"start_time": {"$lte": int(datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc).timestamp())}})
        if ranges:
            where = {"$and": ranges} if len(ranges) > 1 else ranges[0]

        try:
            hits = chroma_store.query_by_vector(vector, n=min(n, 30), where=where)
        except Exception as exc:
            logger.exception("chroma query failed")
            raise ToolError("recommendations temporarily unavailable") from exc

        if not hits:
            return []

        id_to_score = {h.event_id: h.similarity_score for h in hits}
        rows = session.query(Event).filter(Event.id.in_(id_to_score.keys())).all()
        return sorted(
            (_event_to_summary(r, similarity_score=id_to_score[r.id]) for r in rows),
            key=lambda d: d["similarity_score"] or 0.0,
            reverse=True,
        )
    finally:
        session.close()


@tool
def record_feedback(event_id: str, sentiment: str, comment: str | None = None) -> dict:
    """Record thumbs feedback on an event.

    Args:
        event_id: Event ID being reacted to.
        sentiment: 'like' or 'dislike'.
        comment: Optional free-text comment.
    """
    if sentiment not in ("like", "dislike"):
        raise ToolError("sentiment must be 'like' or 'dislike'")
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        if not session.query(Event).filter_by(id=event_id).first():
            raise ToolError("event not found")
        existing = session.query(Feedback).filter_by(user_id=user_id, event_id=event_id).first()
        if existing:
            existing.sentiment = sentiment
            existing.comment = comment
        else:
            import uuid as _uuid
            session.add(Feedback(
                id=str(_uuid.uuid4()),
                user_id=user_id,
                event_id=event_id,
                sentiment=sentiment,
                comment=comment,
            ))
        user = session.query(User).filter_by(id=user_id).one()
        user.taste_summary_dirty = True
        session.commit()
        if sentiment == "like":
            refresh_taste_centroid(session, user_id)
            session.commit()
        return {"status": "ok"}
    finally:
        session.close()


ALL_TOOLS = [
    search_events,
    get_recommendations,
    record_feedback,
    save_to_calendar,
    get_calendar,
    get_user_profile,
    update_user_profile,
]


def select_tools(enabled_names: list[str] | None = None) -> list:
    if enabled_names is None:
        return ALL_TOOLS
    by_name = {t.name: t for t in ALL_TOOLS}
    return [by_name[n] for n in enabled_names if n in by_name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_tools.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/agent/test_tools.py
git commit -m "feat(agent): add get_recommendations and record_feedback tools"
```

---

## Task 12: Prompts and runtime

**Files:**
- Modify: `backend/app/agent/prompts.py`
- Create: `backend/app/agent/runtime.py`
- Create: `backend/tests/agent/test_runtime.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/agent/test_runtime.py`:

```python
from unittest.mock import patch

from app.agent import runtime


@patch("app.agent.runtime.create_react_agent")
@patch("app.agent.runtime.SqliteSaver")
@patch("app.agent.runtime.build_llm")
def test_build_agent_wires_llm_tools_and_checkpointer(mock_llm, mock_saver, mock_create):
    mock_llm.return_value = "FAKE_LLM"
    mock_saver.from_conn_string.return_value.__enter__ = lambda s: "FAKE_CHECKPOINTER"
    mock_saver.from_conn_string.return_value.__exit__ = lambda *a: None

    runtime.build_agent()

    mock_llm.assert_called_once()
    args, kwargs = mock_create.call_args
    assert kwargs["model"] == "FAKE_LLM"
    assert len(kwargs["tools"]) == 7
    tool_names = {t.name for t in kwargs["tools"]}
    assert tool_names == {
        "search_events", "get_recommendations", "record_feedback",
        "save_to_calendar", "get_calendar", "get_user_profile",
        "update_user_profile",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/agent/test_runtime.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Fill in prompts**

Replace `backend/app/agent/prompts.py` entirely:

```python
"""Agent prompt templates."""

SUMMARY_PROMPT = """\
You are summarising a user's event taste based on their reactions.

Interests (stated): {interests}
About-me: {about_me}

Recent feedback (newest first):
{feedback}

Recently saved:
{saved}

Write a single paragraph of at most 80 words capturing the user's taste —
what they consistently like, what they dislike, and any patterns
(venue type, vibe, day of week). Use natural language. No lists.
"""

CURATION_PROMPT = """\
You are a Hamburg event concierge picking today's digest for a user.

USER PROFILE
  Interests: {interests}
  About-me: {about_me}
  Distilled taste: {taste_summary}

TODAY'S CANDIDATE POOL (next 7 days, JSON):
{event_pool}

Your job: pick 3 to 5 events from the pool that this specific user is most
likely to love today. For each pick, write a 1-2 sentence justification
grounded in the user's interests, taste summary, or stated about-me — not
generic praise of the event.

If helpful, you MAY call get_recommendations to surface events ranked by
taste-vector similarity. You do not need to use every tool.

Return your final answer in the structured output format.
"""

CONVERSATIONAL_PROMPT = """\
You are a Hamburg event concierge for one specific user. Today is {today}.

USER PROFILE
  Interests: {interests}
  About-me: {about_me}
  Distilled taste: {taste_summary}

You have tools for searching events, getting personalised recommendations,
recording feedback, saving to the calendar, and reading/updating the
user's profile. Use them when they will help.

Be concise. When you refer to a specific event by name, also mention its
ID in the form [event:ID] so the UI can render the card inline.
Do not invent events that are not in the database. If a tool returns no
results, say so honestly.
"""
```

- [ ] **Step 4: Implement runtime**

`backend/app/agent/runtime.py`:

```python
"""Build the LangGraph agent (a single compiled graph reused for all requests)."""
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.llm import build_llm
from app.agent.tools import select_tools
from app.config import settings


def build_agent(tools_enabled: list[str] | None = None):
    """Compile a ReAct agent. Reused across requests; per-request state is
    keyed by thread_id passed at invocation time."""
    llm = build_llm()
    tools = select_tools(tools_enabled)
    saver_ctx = SqliteSaver.from_conn_string(settings.checkpointer_path)
    checkpointer = saver_ctx.__enter__()
    # Note: The SqliteSaver context is kept open for the lifetime of the app.
    # FastAPI startup creates it; shutdown does not need to release it since
    # the process exits.
    return create_react_agent(model=llm, tools=tools, checkpointer=checkpointer)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd backend && pytest tests/agent/test_runtime.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/prompts.py backend/app/agent/runtime.py backend/tests/agent/test_runtime.py
git commit -m "feat(agent): add prompts and runtime (create_react_agent builder)"
```

---

## Task 13: API deps — X-User-Id middleware + agent dependency

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/deps.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/api/__init__.py` (already exists per glob — skip if so)
- Create: `backend/tests/api/test_deps.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/api/test_deps.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import current_user_id_middleware
from app.agent.memory import get_current_user_id


def _make_app():
    app = FastAPI()
    app.middleware("http")(current_user_id_middleware)

    @app.get("/whoami")
    def whoami():
        return {"user_id": get_current_user_id()}

    return TestClient(app)


def test_default_user_id_when_header_missing():
    client = _make_app()
    r = client.get("/whoami")
    assert r.json() == {"user_id": "local"}


def test_user_id_from_header():
    client = _make_app()
    r = client.get("/whoami", headers={"X-User-Id": "alice"})
    assert r.json() == {"user_id": "alice"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/api/test_deps.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement middleware + db dep**

`backend/app/api/deps.py`:

```python
"""Shared FastAPI dependencies and middleware."""
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.agent.memory import set_current_user_id
from app.config import settings
from app.db.session import SessionLocal


async def current_user_id_middleware(request: Request, call_next):
    user_id = request.headers.get("X-User-Id") or settings.default_user_id
    set_current_user_id(user_id)
    try:
        return await call_next(request)
    finally:
        set_current_user_id(None)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]
```

- [ ] **Step 4: Register middleware in main.py**

Update `backend/app/main.py` to:

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.api.deps import current_user_id_middleware
from app.ingestion.scheduler import create_scheduler, run_ingestion

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Ingestion scheduler started (daily 04:00 Europe/Berlin)")
    yield
    scheduler.shutdown(wait=False)
    logger.info("Ingestion scheduler stopped")


app = FastAPI(title="Event Tracker API", lifespan=lifespan)
app.middleware("http")(current_user_id_middleware)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingestion/run", status_code=200)
def trigger_ingestion() -> dict:
    try:
        report = run_ingestion()
        return {"inserted": report.inserted, "updated": report.updated, "skipped": report.skipped}
    except Exception as exc:
        logger.exception("Manual ingestion run failed")
        raise HTTPException(status_code=500, detail="Ingestion failed") from exc
```

Routers are added in subsequent tasks; main.py imports them as we go.

- [ ] **Step 5: Add a `client` fixture for route tests**

Append to `backend/tests/conftest.py`:

```python
from fastapi.testclient import TestClient


@pytest.fixture
def client(db_session, monkeypatch):
    """TestClient with the app's get_db dependency overridden to the in-memory session."""
    from app.main import app
    from app.api.deps import get_db

    def override_db():
        try:
            yield db_session
        finally:
            pass  # fixture controls cleanup

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd backend && pytest tests/api/test_deps.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/deps.py backend/app/main.py backend/tests/conftest.py backend/tests/api/test_deps.py
git commit -m "feat(api): add X-User-Id middleware and shared FastAPI deps"
```

---

## Task 14: Routes — profile

**Files:**
- Create: `backend/app/api/routes_profile.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/api/test_routes_profile.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_profile.py`:

```python
import pytest

from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], about_me="x",
             taste_summary="loves jazz", taste_summary_dirty=False)
    db_session.add(u)
    db_session.commit()
    return u


def test_get_profile(client, user):
    r = client.get("/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["city"] == "Hamburg"
    assert body["interest_tags"] == ["music"]
    assert body["taste_summary"] == "loves jazz"


def test_put_profile_updates_and_marks_dirty(client, user, db_session):
    r = client.put("/profile", json={"interest_tags": ["music", "tech"], "about_me": "new"})
    assert r.status_code == 200
    db_session.refresh(user)
    assert user.interest_tags == ["music", "tech"]
    assert user.about_me == "new"
    assert user.taste_summary_dirty is True


def test_post_onboard_creates_when_missing(client, db_session):
    r = client.post("/profile/onboard", json={"interest_tags": ["arts"], "about_me": "hi"})
    assert r.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.interest_tags == ["arts"]
    assert u.about_me == "hi"


def test_post_onboard_idempotent_updates_existing(client, user, db_session):
    r = client.post("/profile/onboard", json={"interest_tags": ["tech"]})
    assert r.status_code == 200
    db_session.refresh(user)
    assert user.interest_tags == ["tech"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_profile.py -v`
Expected: FAIL — route does not exist (404).

- [ ] **Step 3: Implement routes_profile.py**

`backend/app/api/routes_profile.py`:

```python
from fastapi import APIRouter, HTTPException

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import User
from app.schemas.common import UserSettings
from app.schemas.profile import OnboardingRequest, UserProfileResponse, UserProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


def _to_response(u: User) -> UserProfileResponse:
    return UserProfileResponse(
        city=u.city,
        interest_tags=u.interest_tags,
        about_me=u.about_me,
        taste_summary=u.taste_summary,
        settings=UserSettings(**(u.settings or {})),
    )


@router.get("", response_model=UserProfileResponse)
def get_profile(db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return _to_response(u)


@router.put("", response_model=UserProfileResponse)
def update_profile(payload: UserProfileUpdate, db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    if payload.interest_tags is not None:
        u.interest_tags = payload.interest_tags
    if payload.about_me is not None:
        u.about_me = payload.about_me
    u.taste_summary_dirty = True
    db.commit()
    db.refresh(u)
    return _to_response(u)


@router.post("/onboard", response_model=UserProfileResponse)
def onboard(payload: OnboardingRequest, db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        u = User(id=user_id)
        db.add(u)
    u.interest_tags = payload.interest_tags
    u.about_me = payload.about_me
    u.taste_summary_dirty = True
    db.commit()
    db.refresh(u)
    return _to_response(u)
```

- [ ] **Step 4: Register router in main.py**

Update `backend/app/main.py` — after `app.middleware(...)`, add:

```python
from app.api import routes_profile
app.include_router(routes_profile.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_profile.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_profile.py backend/app/main.py backend/tests/api/test_routes_profile.py
git commit -m "feat(api): add /profile routes (get, update, onboard)"
```

---

## Task 15: Routes — events

**Files:**
- Create: `backend/app/api/routes_events.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_routes_events.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_events.py`:

```python
from datetime import datetime, timezone

import pytest

from app.db.models import Event, Feedback, SavedEvent, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    for i, cat in enumerate(["music", "tech", "music"]):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", category=cat, source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i, tzinfo=timezone.utc),
        ))
    db_session.commit()


def test_list_events_paginated(client, setup):
    r = client.get("/events?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["events"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_list_events_category_filter(client, setup):
    r = client.get("/events?category=tech")
    body = r.json()
    assert body["total"] == 1
    assert body["events"][0]["category"] == "tech"


def test_list_events_includes_user_context(client, setup, db_session):
    db_session.add(Feedback(id="f1", user_id="local", event_id="e0",
                             sentiment="like", comment="great"))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="e0"))
    db_session.commit()
    r = client.get("/events?category=music")
    events = {e["id"]: e for e in r.json()["events"]}
    assert events["e0"]["user_sentiment"] == "like"
    assert events["e0"]["user_comment"] == "great"
    assert events["e0"]["is_saved"] is True
    assert events["e2"]["is_saved"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_events.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement routes_events.py**

`backend/app/api/routes_events.py`:

```python
from fastapi import APIRouter, Query

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Event, Feedback, SavedEvent
from app.schemas.common import EventWithContext
from app.schemas.events import EventsFeedResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventsFeedResponse)
def list_events(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
) -> EventsFeedResponse:
    user_id = get_current_user_id()
    q = db.query(Event).filter(Event.is_active == True)  # noqa: E712
    if category:
        q = q.filter(Event.category == category)
    total = q.count()
    rows = (
        q.order_by(Event.start_datetime.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [r.id for r in rows]
    fb_map = {
        f.event_id: f
        for f in db.query(Feedback).filter(Feedback.user_id == user_id, Feedback.event_id.in_(ids)).all()
    }
    saved_set = {
        s.event_id
        for s in db.query(SavedEvent).filter(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids)).all()
    }

    events = []
    for r in rows:
        fb = fb_map.get(r.id)
        events.append(EventWithContext(
            id=r.id, title=r.title, summary=r.summary,
            start_datetime=r.start_datetime, end_datetime=r.end_datetime,
            venue_name=r.venue_name, venue_address=r.venue_address,
            category=r.category, tags=r.tags,
            price_min=r.price_min, price_max=r.price_max,
            is_free=r.is_free, currency=r.currency,
            image_url=r.image_url, source_url=r.source_url, source=r.source,
            is_active=r.is_active,
            user_sentiment=fb.sentiment if fb else None,
            user_comment=fb.comment if fb else None,
            is_saved=r.id in saved_set,
        ))

    return EventsFeedResponse(events=events, total=total, page=page, page_size=page_size)
```

- [ ] **Step 4: Register router**

Append in `backend/app/main.py` near other includes:

```python
from app.api import routes_events
app.include_router(routes_events.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_events.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_events.py backend/app/main.py backend/tests/api/test_routes_events.py
git commit -m "feat(api): add GET /events with pagination and user context"
```

---

## Task 16: Routes — feedback

**Files:**
- Create: `backend/app/api/routes_feedback.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_routes_feedback.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_feedback.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import Event, Feedback, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=["music"]))
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite",
        title="Jazz", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.commit()


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_like_inserts_and_refreshes(mock_refresh, client, setup, db_session):
    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "like", "comment": "loved it"})
    assert r.status_code == 200
    row = db_session.query(Feedback).filter_by(event_id="e1").one()
    assert row.sentiment == "like"
    assert row.comment == "loved it"
    user = db_session.query(User).filter_by(id="local").one()
    assert user.taste_summary_dirty is True
    mock_refresh.assert_called_once()


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_dislike_skips_refresh(mock_refresh, client, setup):
    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "dislike"})
    assert r.status_code == 200
    mock_refresh.assert_not_called()


def test_post_feedback_unknown_event_404(client, setup):
    r = client.post("/feedback", json={"event_id": "nope", "sentiment": "like"})
    assert r.status_code == 404


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_upserts_on_repeat(mock_refresh, client, setup, db_session):
    client.post("/feedback", json={"event_id": "e1", "sentiment": "like"})
    client.post("/feedback", json={"event_id": "e1", "sentiment": "dislike", "comment": "changed mind"})
    rows = db_session.query(Feedback).filter_by(event_id="e1").all()
    assert len(rows) == 1
    assert rows[0].sentiment == "dislike"
    assert rows[0].comment == "changed mind"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_feedback.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement routes_feedback.py**

`backend/app/api/routes_feedback.py`:

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agent.memory import get_current_user_id, refresh_taste_centroid
from app.api.deps import DbSession
from app.db.models import Event, Feedback, User
from app.schemas.feedback import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
def post_feedback(payload: FeedbackCreate, db: DbSession) -> FeedbackResponse:
    user_id = get_current_user_id()
    if not db.query(Event).filter_by(id=payload.event_id).first():
        raise HTTPException(status_code=404, detail="event not found")

    existing = db.query(Feedback).filter_by(user_id=user_id, event_id=payload.event_id).first()
    if existing:
        existing.sentiment = payload.sentiment
        existing.comment = payload.comment
        existing.updated_at = datetime.now(timezone.utc)
        fb = existing
    else:
        fb = Feedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=payload.event_id,
            sentiment=payload.sentiment,
            comment=payload.comment,
        )
        db.add(fb)

    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is not None:
        user.taste_summary_dirty = True
    db.commit()
    db.refresh(fb)

    if payload.sentiment == "like":
        refresh_taste_centroid(db, user_id)
        db.commit()

    return FeedbackResponse(
        id=fb.id, event_id=fb.event_id, sentiment=fb.sentiment,
        comment=fb.comment, created_at=fb.created_at, updated_at=fb.updated_at,
    )
```

- [ ] **Step 4: Register router**

Append in `backend/app/main.py`:

```python
from app.api import routes_feedback
app.include_router(routes_feedback.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_feedback.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_feedback.py backend/app/main.py backend/tests/api/test_routes_feedback.py
git commit -m "feat(api): add POST /feedback with centroid refresh on like"
```

---

## Task 17: Routes — calendar

**Files:**
- Create: `backend/app/api/routes_calendar.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_routes_calendar.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_calendar.py`:

```python
from datetime import datetime, timezone

import pytest

from app.db.models import Event, SavedEvent, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite",
        title="Jazz", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.commit()


def test_get_calendar_empty(client, setup):
    r = client.get("/calendar")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_post_calendar_saves(client, setup, db_session):
    r = client.post("/calendar", json={"event_id": "e1"})
    assert r.status_code == 200
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1


def test_post_calendar_idempotent(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    client.post("/calendar", json={"event_id": "e1"})
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1


def test_post_calendar_unknown_event_404(client, setup):
    r = client.post("/calendar", json={"event_id": "nope"})
    assert r.status_code == 404


def test_delete_calendar(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    r = client.delete("/calendar/e1")
    assert r.status_code == 204
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 0


def test_get_calendar_returns_entries(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    r = client.get("/calendar")
    body = r.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["event"]["id"] == "e1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_calendar.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement routes_calendar.py**

`backend/app/api/routes_calendar.py`:

```python
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Event, SavedEvent
from app.schemas.calendar import CalendarEntry, CalendarResponse
from app.schemas.common import EventCard

router = APIRouter(prefix="/calendar", tags=["calendar"])


class SaveRequest(BaseModel):
    event_id: str


def _event_to_card(e: Event) -> EventCard:
    return EventCard(
        id=e.id, title=e.title, summary=e.summary,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
    )


@router.get("", response_model=CalendarResponse)
def get_calendar(db: DbSession) -> CalendarResponse:
    user_id = get_current_user_id()
    rows = (
        db.query(SavedEvent, Event)
        .join(Event, Event.id == SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id)
        .order_by(Event.start_datetime.asc())
        .all()
    )
    entries = [
        CalendarEntry(id=s.id, event=_event_to_card(e), saved_at=s.saved_at)
        for s, e in rows
    ]
    return CalendarResponse(entries=entries)


@router.post("", response_model=CalendarEntry)
def save_to_calendar(payload: SaveRequest, db: DbSession) -> CalendarEntry:
    user_id = get_current_user_id()
    e = db.query(Event).filter_by(id=payload.event_id).one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="event not found")
    existing = db.query(SavedEvent).filter_by(user_id=user_id, event_id=payload.event_id).one_or_none()
    if existing is None:
        existing = SavedEvent(id=str(uuid.uuid4()), user_id=user_id, event_id=payload.event_id)
        db.add(existing)
        db.commit()
        db.refresh(existing)
    return CalendarEntry(id=existing.id, event=_event_to_card(e), saved_at=existing.saved_at)


@router.delete("/{event_id}", status_code=204)
def unsave(event_id: str, db: DbSession) -> Response:
    user_id = get_current_user_id()
    row = db.query(SavedEvent).filter_by(user_id=user_id, event_id=event_id).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Register router**

Append in `backend/app/main.py`:

```python
from app.api import routes_calendar
app.include_router(routes_calendar.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_calendar.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_calendar.py backend/app/main.py backend/tests/api/test_routes_calendar.py
git commit -m "feat(api): add /calendar routes (get, save, unsave)"
```

---

## Task 18: Routes — digest

**Files:**
- Create: `backend/app/api/routes_digest.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_routes_digest.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_digest.py`:

```python
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import LLMDigestPick, LLMDigestResponse
from app.db.models import DigestCache, Event, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=["music"],
                        taste_summary="loves jazz", taste_summary_dirty=False))
    for i in range(5):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", description=f"desc {i}", category="music",
            source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i, tzinfo=timezone.utc),
        ))
    db_session.commit()


def _fake_agent_with_picks(picks):
    agent = MagicMock()
    response = LLMDigestResponse(picks=[LLMDigestPick(event_id=p, justification="because " + p) for p in picks])
    agent.invoke.return_value = {"structured_response": response}
    return agent


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_generates_on_miss_and_caches(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    r = client.get("/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-06-09"
    assert len(body["picks"]) == 3
    assert body["picks"][0]["event"]["id"] == "e0"
    assert body["is_cached"] is False
    assert db_session.query(DigestCache).filter_by(user_id="local").count() == 1


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_returns_cache_without_invoking_llm(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")  # populate cache
    mock_agent.reset_mock()
    r = client.get("/digest")
    body = r.json()
    assert body["is_cached"] is True
    mock_agent.return_value.invoke.assert_not_called()


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_refresh_overwrites_cache(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")

    mock_agent.return_value = _fake_agent_with_picks(["e3", "e4", "e0"])
    r = client.post("/digest/refresh")
    body = r.json()
    assert {p["event"]["id"] for p in body["picks"]} == {"e3", "e4", "e0"}


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_502_when_agent_returns_too_few_picks(mock_agent, _today, client, setup):
    agent = MagicMock()
    agent.invoke.return_value = {"structured_response": None}
    mock_agent.return_value = agent
    r = client.get("/digest")
    assert r.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_digest.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement routes_digest.py**

`backend/app/api/routes_digest.py`:

```python
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.memory import get_current_user_id, refresh_taste_summary
from app.agent.prompts import CURATION_PROMPT
from app.agent.schemas import LLMDigestResponse
from app.api.deps import DbSession
from app.db.models import DigestCache, Event, User
from app.schemas.common import EventCard
from app.schemas.digest import DigestPick, DigestResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest", tags=["digest"])


_agent_singleton = None


def get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        from app.agent.runtime import build_agent
        _agent_singleton = build_agent()
    return _agent_singleton


def _get_today() -> date:
    return datetime.now(timezone.utc).date()


def _event_to_card(e: Event) -> EventCard:
    return EventCard(
        id=e.id, title=e.title, summary=e.summary,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
    )


def _serialise_event_for_prompt(e: Event) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "description": (e.description or "")[:500],
        "category": e.category,
        "start_datetime": e.start_datetime.isoformat(),
        "venue_name": e.venue_name,
        "is_free": e.is_free,
        "price_min": e.price_min,
    }


def _candidate_pool(db, today: date) -> list[Event]:
    end = datetime.combine(today + timedelta(days=7), datetime.max.time(), tzinfo=timezone.utc)
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    return (
        db.query(Event)
        .filter(Event.is_active == True, Event.start_datetime >= start, Event.start_datetime <= end)  # noqa: E712
        .order_by(Event.start_datetime.asc())
        .limit(150)
        .all()
    )


def _build_response(picks_raw: list[dict], db, today: date, generated_at: datetime, is_cached: bool) -> DigestResponse:
    ids = [p["event_id"] for p in picks_raw]
    rows = {r.id: r for r in db.query(Event).filter(Event.id.in_(ids)).all()}
    picks: list[DigestPick] = []
    for p in picks_raw:
        e = rows.get(p["event_id"])
        if e is None:
            continue
        picks.append(DigestPick(event=_event_to_card(e), justification=p["justification"]))
    return DigestResponse(date=today, picks=picks, generated_at=generated_at, is_cached=is_cached)


def _generate_digest(db, user: User, today: date) -> DigestResponse:
    refresh_taste_summary(db, user.id)
    db.commit()
    db.refresh(user)

    pool = _candidate_pool(db, today)
    if not pool:
        raise HTTPException(status_code=503, detail="no events available")

    prompt = CURATION_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        taste_summary=user.taste_summary or "(not yet generated)",
        event_pool=json.dumps([_serialise_event_for_prompt(e) for e in pool], indent=2),
    )

    agent = get_agent()
    result = agent.invoke(
        {"messages": [SystemMessage(content=prompt), HumanMessage(content="Pick today's events.")]},
        config={"configurable": {"thread_id": f"digest:{user.id}:{today.isoformat()}"}},
        response_format=LLMDigestResponse,
    )
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if structured is None or not getattr(structured, "picks", None) or len(structured.picks) < 3:
        logger.warning("digest: agent returned malformed structured_response: %r", result)
        raise HTTPException(status_code=502, detail="could not generate digest, please refresh")

    picks_raw = [{"event_id": p.event_id, "justification": p.justification} for p in structured.picks]
    generated_at = datetime.now(timezone.utc)

    db.add(DigestCache(
        id=str(uuid.uuid4()),
        user_id=user.id,
        date=today,
        picks=picks_raw,
        generated_at=generated_at,
    ))
    db.commit()

    return _build_response(picks_raw, db, today, generated_at, is_cached=False)


def _load_user_or_404(db, user_id: str) -> User:
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return u


@router.get("", response_model=DigestResponse)
def get_digest(db: DbSession) -> DigestResponse:
    user_id = get_current_user_id()
    user = _load_user_or_404(db, user_id)
    today = _get_today()

    cached = db.query(DigestCache).filter_by(user_id=user_id, date=today).one_or_none()
    if cached:
        return _build_response(cached.picks, db, today, cached.generated_at, is_cached=True)

    return _generate_digest(db, user, today)


@router.post("/refresh", response_model=DigestResponse)
def refresh_digest(db: DbSession) -> DigestResponse:
    user_id = get_current_user_id()
    user = _load_user_or_404(db, user_id)
    today = _get_today()

    existing = db.query(DigestCache).filter_by(user_id=user_id, date=today).one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()
    return _generate_digest(db, user, today)
```

- [ ] **Step 4: Register router**

Append in `backend/app/main.py`:

```python
from app.api import routes_digest
app.include_router(routes_digest.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_digest.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_digest.py backend/app/main.py backend/tests/api/test_routes_digest.py
git commit -m "feat(api): add /digest (cached) and /digest/refresh endpoints"
```

---

## Task 19: Routes — chat (SSE)

**Files:**
- Create: `backend/app/api/routes_chat.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_routes_chat.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_routes_chat.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import ChatMessage, User


@pytest.fixture
def user(db_session):
    db_session.add(User(id="local", interest_tags=["music"],
                        taste_summary="loves jazz", taste_summary_dirty=False))
    db_session.commit()


def _sse_events(response_text: str) -> list[dict]:
    events = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@patch("app.api.routes_chat.get_agent")
def test_chat_streams_tokens_and_done(mock_get_agent, client, user, db_session):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        yield ("messages", (MagicMock(content="Hello "), {"langgraph_node": "agent"}))
        yield ("messages", (MagicMock(content="there!"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    assert [e["content"] for e in events if e["type"] == "token"] == ["Hello ", "there!"]


@patch("app.api.routes_chat.get_agent")
def test_chat_mirrors_user_and_assistant_messages_to_db(mock_get_agent, client, user, db_session):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        yield ("messages", (MagicMock(content="reply"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(ChatMessage).filter_by(session_id="s1").order_by(ChatMessage.created_at).all()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "hi"
    assert rows[1].content == "reply"


@patch("app.api.routes_chat.get_agent")
def test_chat_emits_error_event_on_agent_exception(mock_get_agent, client, user):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"] or "agent error" in events[-1]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/api/test_routes_chat.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement routes_chat.py**

`backend/app/api/routes_chat.py`:

```python
import json
import logging
from datetime import date, datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.memory import get_current_user_id, record_message, refresh_taste_summary
from app.agent.prompts import CONVERSATIONAL_PROMPT
from app.api.deps import DbSession
from app.db.models import User
from app.schemas.chat import ChatRequest
from app.schemas.common import ChatTokenUsage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_agent_singleton = None


def get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        from app.agent.runtime import build_agent
        _agent_singleton = build_agent()
    return _agent_singleton


async def _stream_chat(payload: ChatRequest, db) -> AsyncIterator[dict]:
    user_id = get_current_user_id()
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        yield {"event": "message", "data": json.dumps({"type": "error", "message": "user not onboarded"})}
        return

    refresh_taste_summary(db, user_id)
    db.commit()
    db.refresh(user)

    record_message(db, payload.session_id, user_id, "user", payload.message)
    db.commit()

    system = CONVERSATIONAL_PROMPT.format(
        today=date.today().isoformat(),
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        taste_summary=user.taste_summary or "(not yet generated)",
    )

    assistant_buffer: list[str] = []
    try:
        agent = get_agent()
        async for mode, item in agent.astream(
            {"messages": [SystemMessage(content=system), HumanMessage(content=payload.message)]},
            config={"configurable": {"thread_id": payload.session_id}},
            stream_mode="messages",
        ):
            if mode != "messages":
                continue
            message, _meta = item
            if isinstance(message, AIMessage):
                if isinstance(message.content, str) and message.content:
                    assistant_buffer.append(message.content)
                    yield {"event": "message", "data": json.dumps({"type": "token", "content": message.content})}
                for call in getattr(message, "tool_calls", []) or []:
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "tool_start", "tool_name": call["name"]}),
                    }
            elif isinstance(message, ToolMessage):
                status = "error" if str(message.content).lower().startswith("error") else "ok"
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "tool_end", "tool_name": message.name or "unknown", "status": status}),
                }
    except Exception as exc:
        logger.exception("chat stream failed")
        yield {"event": "message", "data": json.dumps({"type": "error", "message": f"agent error: {exc}"})}
        return

    full_text = "".join(assistant_buffer)
    if full_text:
        record_message(db, payload.session_id, user_id, "assistant", full_text)
        db.commit()

    yield {
        "event": "message",
        "data": json.dumps({
            "type": "done",
            "token_usage": ChatTokenUsage(input_tokens=0, output_tokens=0, estimated_cost_usd=0.0).model_dump(),
        }),
    }


@router.post("/chat")
async def chat(payload: ChatRequest, db: DbSession):
    return EventSourceResponse(_stream_chat(payload, db))
```

- [ ] **Step 4: Register router**

Append in `backend/app/main.py`:

```python
from app.api import routes_chat
app.include_router(routes_chat.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/api/test_routes_chat.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_chat.py backend/app/main.py backend/tests/api/test_routes_chat.py
git commit -m "feat(api): add POST /chat SSE endpoint with mirror to chat_messages"
```

---

## Task 20: Integration test — digest cycle end-to-end with fake LLM

**Files:**
- Create: `backend/tests/integration/__init__.py` (empty)
- Create: `backend/tests/integration/test_digest_cycle.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_digest_cycle.py`:

```python
"""End-to-end digest exercises: events fixture → /digest → cache hit on second call."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import LLMDigestPick, LLMDigestResponse
from app.db.models import DigestCache, Event, User


@pytest.fixture
def populated(db_session):
    db_session.add(User(id="local", interest_tags=["music"], taste_summary="loves jazz", taste_summary_dirty=False))
    for i in range(8):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", description="d", category="music",
            source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i % 3, tzinfo=timezone.utc),
        ))
    db_session.commit()


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_full_cycle_caches(mock_agent, _today, client, populated, db_session):
    response = LLMDigestResponse(picks=[
        LLMDigestPick(event_id=f"e{i}", justification=f"justification {i}") for i in range(4)
    ])
    fake = MagicMock()
    fake.invoke.return_value = {"structured_response": response}
    mock_agent.return_value = fake

    r1 = client.get("/digest")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["is_cached"] is False
    assert len(body1["picks"]) == 4

    assert db_session.query(DigestCache).filter_by(user_id="local").count() == 1
    fake.invoke.reset_mock()

    r2 = client.get("/digest")
    body2 = r2.json()
    assert body2["is_cached"] is True
    assert [p["event"]["id"] for p in body2["picks"]] == [p["event"]["id"] for p in body1["picks"]]
    fake.invoke.assert_not_called()
```

- [ ] **Step 2: Run test to verify pass**

Run: `cd backend && pytest tests/integration/test_digest_cycle.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/__init__.py backend/tests/integration/test_digest_cycle.py
git commit -m "test(integration): digest generate-then-cache cycle"
```

---

## Task 21: Integration test — chat SSE end-to-end with fake LLM

**Files:**
- Create: `backend/tests/integration/test_chat_sse.py`

- [ ] **Step 1: Write the test**

`backend/tests/integration/test_chat_sse.py`:

```python
"""End-to-end /chat exercise: fake LLM yields tokens and a tool call,
SSE stream contains expected events, chat_messages rows are written."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import ChatMessage, User


@pytest.fixture
def user(db_session):
    db_session.add(User(id="local", interest_tags=["music"], taste_summary="loves jazz", taste_summary_dirty=False))
    db_session.commit()


def _events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


@patch("app.api.routes_chat.get_agent")
def test_chat_yields_token_tool_done(mock_get_agent, client, user, db_session):
    from langchain_core.messages import AIMessage, ToolMessage

    async def stream(*args, **kwargs):
        yield ("messages", (AIMessage(content="Sure, let me check. ", tool_calls=[]), {}))
        yield ("messages", (AIMessage(content="", tool_calls=[{"name": "search_events", "args": {}, "id": "t1"}]), {}))
        yield ("messages", (ToolMessage(content="[]", tool_call_id="t1", name="search_events"), {}))
        yield ("messages", (AIMessage(content="Nothing matched.", tool_calls=[]), {}))

    fake = MagicMock()
    fake.astream = stream
    mock_get_agent.return_value = fake

    with client.stream("POST", "/chat", json={"session_id": "sess1", "message": "anything good?"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _events(body)
    types = [e["type"] for e in events]
    assert "token" in types
    assert "tool_start" in types
    assert "tool_end" in types
    assert types[-1] == "done"
    assert next(e for e in events if e["type"] == "tool_start")["tool_name"] == "search_events"

    rows = db_session.query(ChatMessage).filter_by(session_id="sess1").all()
    assert {r.role for r in rows} == {"user", "assistant"}
```

- [ ] **Step 2: Run test to verify pass**

Run: `cd backend && pytest tests/integration/test_chat_sse.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_chat_sse.py
git commit -m "test(integration): chat SSE token + tool_start + tool_end + done sequence"
```

---

## Task 22: Final full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the full test suite**

Run: `cd backend && pytest -v`
Expected: ALL tests pass (existing + new). Roughly 80+ tests.

- [ ] **Step 2: If any test fails**

Read the failure, fix the regression, re-run. Do not `--no-verify` or skip tests.

- [ ] **Step 3: Smoke test the FastAPI app locally (manual, optional but recommended)**

```bash
cd backend
OPENROUTER_API_KEY=sk-or-... OPENAI_API_KEY=sk-... uvicorn app.main:app --reload
```

In another terminal:
```bash
curl -X POST http://localhost:8000/profile/onboard \
  -H 'Content-Type: application/json' \
  -d '{"interest_tags":["music","tech"]}'
curl http://localhost:8000/profile
```

Both should return JSON; `/profile` returns the onboarded user.

- [ ] **Step 4: Update task status and commit nothing extra**

If anything in `backend/data/` ended up committed (it shouldn't, per Task 1's `.gitignore`), remove and recommit.

- [ ] **Step 5: Optional final commit if README / docs need touch-ups**

Skipped by default — only commit if you genuinely changed user-facing docs as part of this exercise.

---

## Self-review

(Performed during plan writing; included here for the reader.)

**Spec coverage:**
- §2 Architecture overview → Tasks 1, 3, 4, 6, 7, 8, 9-11, 12, 13.
- §3 LLM client → Task 7.
- §4 Graph & prompts → Tasks 8 (prompt stub), 11/12 (prompts + runtime).
- §5 Tools → Tasks 9, 10, 11.
- §6 Memory → Tasks 2 (migration), 8 (helpers).
- §7 RAG → Tasks 3, 4, 5.
- §8 API surface → Tasks 13, 14, 15, 16, 17, 18, 19.
- §9 Error handling → covered inside individual route/tool tests (404 unknown event, 502 malformed digest, SSE `error` event on agent exception).
- §10 Testing → unit tests in every task; integration tests in Tasks 20 + 21.

**Placeholder scan:** Prompts in Task 8 are explicitly marked `PLACEHOLDER` with a pointer to Task 12 that replaces them — this is an intentional staged build, not an unfilled gap. No "TBD" anywhere else.

**Type consistency:** `Sentiment` is `"like"`/`"dislike"` everywhere. `EventCard` (from `app/schemas/common.py`) used by both `/digest` and `/calendar`. `LLMDigestResponse` / `LLMDigestPick` are the LLM-facing internal models; `DigestResponse` / `DigestPick` (from `app/schemas/digest.py`) are the API models. `select_tools` defined in Task 11 and used in Task 12. `get_agent` defined separately in `routes_digest.py` and `routes_chat.py` for independent singleton ownership.
