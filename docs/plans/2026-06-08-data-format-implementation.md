# Data Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the complete data-format contract — SQLAlchemy DB models, Pydantic API schemas, the `NormalizedEvent` ingestion contract, plus a Next.js frontend with matching TypeScript types and JSON fixtures — so ingestion-pipeline work and frontend-with-mock-data work can proceed in parallel.

**Architecture:** Backend uses SQLAlchemy 2.0 (DeclarativeBase) with Alembic migrations, separate Pydantic v2 schemas for API I/O, and a `NormalizedEvent` Pydantic model as the canonical ingestion-adapter output. Frontend is Next.js 14 (App Router, TypeScript) with a `lib/api.ts` that switches between fetching from the FastAPI backend and reading static JSON fixtures via `NEXT_PUBLIC_MOCK_MODE`.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0, Alembic, Pydantic v2, pytest, Next.js 14, TypeScript, Tailwind CSS.

**Source spec:** `docs/specs/2026-06-08-data-format-design.md`.

**Out of scope (later plans):** FastAPI route handlers, source adapters (Eventbrite, Ticketmaster, Hamburg scraper), the LangGraph agent, Chroma embedding pipeline, scheduler, observability.

---

## Phases at a glance

1. Backend scaffolding (Tasks 1–3)
2. SQLAlchemy models (Tasks 4–9)
3. Initial Alembic migration (Task 10)
4. Pydantic API schemas (Tasks 11–18)
5. `NormalizedEvent` ingestion contract (Task 19)
6. Frontend scaffolding (Task 20)
7. TypeScript types (Task 21)
8. JSON fixtures + contract test (Tasks 22–23)
9. `lib/api.ts` with mock switching (Task 24)
10. `.env.example` files (Task 25)

The existing root-level `.venv` is reused for backend work. All commands assume Windows PowerShell unless noted. Activate the venv first: `.\.venv\Scripts\Activate.ps1`.

---

## Phase 1 — Backend scaffolding

### Task 1: Backend pyproject.toml and package structure

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/README.md`

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "event-tracker-backend"
version = "0.1.0"
description = "Event Tracker backend — FastAPI + LangGraph agent"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0.30",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Write `backend/app/__init__.py`** (empty file)

- [ ] **Step 3: Write `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
```

- [ ] **Step 4: Write `backend/tests/__init__.py`** (empty file)

- [ ] **Step 5: Write `backend/tests/conftest.py`**

```python
"""Shared pytest fixtures for the backend test suite."""
```

(Empty body for now — real fixtures land with the DB tasks.)

- [ ] **Step 6: Write `backend/README.md`**

```markdown
# Event Tracker — Backend

FastAPI + LangGraph agent. See `docs/specs/2026-06-08-event-tracker-tech-design.md` for the architecture overview and `docs/specs/2026-06-08-data-format-design.md` for the data contract.

## Install (from repo root, with `.venv` activated)

```powershell
pip install -e ".\backend[dev]"
```

## Run tests

```powershell
cd backend
pytest
```
```

- [ ] **Step 7: Install the package and verify pytest runs**

Run:
```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev]"
cd backend
pytest
```
Expected: `no tests ran in <time>s` — success exit code.

- [ ] **Step 8: Commit**

```powershell
git add backend/pyproject.toml backend/app backend/tests backend/README.md
git commit -m "chore(backend): scaffold pyproject and package layout"
```

---

### Task 2: SQLAlchemy Base and session

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/tests/db/__init__.py`
- Create: `backend/tests/db/test_session.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_session.py`**

```python
from sqlalchemy import text

from app.db.base import Base
from app.db.session import SessionLocal, engine


def test_engine_is_sqlite_by_default():
    assert engine.url.get_backend_name() == "sqlite"


def test_session_executes_simple_query():
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_base_metadata_is_empty_initially():
    # No models registered yet — sanity check that Base wires up.
    assert Base.metadata.tables == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.base'`.

- [ ] **Step 3: Write `backend/app/db/__init__.py`** (empty file)

- [ ] **Step 4: Write `backend/app/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass
```

- [ ] **Step 5: Write `backend/app/db/session.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session, future=True)
```

- [ ] **Step 6: Create `backend/tests/db/__init__.py`** (empty file)

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/db/test_session.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/db backend/tests/db
git commit -m "feat(backend): add SQLAlchemy Base and session factory"
```

---

### Task 3: Alembic initialization

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/app/db/migrations/env.py` (via `alembic init`, then edited)
- Create: `backend/app/db/migrations/script.py.mako` (via `alembic init`)
- Create: `backend/app/db/migrations/versions/.gitkeep`

- [ ] **Step 1: Run `alembic init`**

```powershell
cd backend
alembic init app/db/migrations
```
Expected: creates `app/db/migrations/` with `env.py`, `script.py.mako`, `versions/`, and `alembic.ini` at `backend/alembic.ini`.

- [ ] **Step 2: Edit `backend/alembic.ini`** — change the `sqlalchemy.url` line:

Replace:
```ini
sqlalchemy.url = driver://user:pass@localhost/dbname
```
with:
```ini
sqlalchemy.url = sqlite:///./event_tracker.db
```

- [ ] **Step 3: Edit `backend/app/db/migrations/env.py`** — wire up `Base.metadata`

Replace the `target_metadata = None` line with:

```python
import os
import sys

# Make the `app` package importable when alembic runs from backend/.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from app.db.base import Base  # noqa: E402
# Import all model modules so their tables register on Base.metadata.
# (Imports added as models are introduced in later tasks.)

target_metadata = Base.metadata
```

- [ ] **Step 4: Add `.gitkeep` to `backend/app/db/migrations/versions/`** so the empty directory is tracked

Create empty file at `backend/app/db/migrations/versions/.gitkeep`.

- [ ] **Step 5: Verify alembic recognizes the config**

Run: `alembic current`
Expected: no error, output like `(empty)` or `INFO  [alembic.runtime.migration] ...`.

- [ ] **Step 6: Commit**

```powershell
git add backend/alembic.ini backend/app/db/migrations
git commit -m "chore(backend): initialize Alembic for SQLite"
```

---

## Phase 2 — SQLAlchemy models

All model tasks share a pattern: write the failing test that asserts schema shape and constraints, then write the model. The test fixture below is referenced by every model test in this phase.

### Task 4: User model

**Files:**
- Create: `backend/app/db/models/__init__.py`
- Create: `backend/app/db/models/user.py`
- Modify: `backend/tests/db/__init__.py` (no change needed; just exists)
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/db/test_user.py`

- [ ] **Step 1: Add shared in-memory DB fixture — `backend/tests/conftest.py`**

```python
"""Shared pytest fixtures for the backend test suite."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite DB with all current model tables created."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

- [ ] **Step 2: Write the failing test — `backend/tests/db/test_user.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

# Import all models so Base.metadata is populated for the fixture.
from app.db.models import user as _user  # noqa: F401
from app.db.models.user import User


def test_user_creation_with_defaults(db_session):
    u = User(id="local", interest_tags=["music", "tech"], settings={})
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    assert u.id == "local"
    assert u.city == "Hamburg"
    assert u.interest_tags == ["music", "tech"]
    assert u.about_me is None
    assert u.taste_summary is None
    assert u.settings == {}
    assert isinstance(u.created_at, datetime)
    assert isinstance(u.updated_at, datetime)


def test_user_id_is_primary_key(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()
    db_session.add(User(id="local", interest_tags=[], settings={}))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/db/test_user.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.models'`.

- [ ] **Step 4: Write `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.user import User

__all__ = ["User"]
```

- [ ] **Step 5: Write `backend/app/db/models/user.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
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
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_user.py -v`
Expected: 2 passed.

- [ ] **Step 7: Update `backend/app/db/migrations/env.py`** — add the model import so Alembic autogenerate sees it

Add after the existing `from app.db.base import Base` line:
```python
from app.db.models import user as _user_model  # noqa: F401
```

- [ ] **Step 8: Commit**

```powershell
git add backend/app/db/models backend/tests/conftest.py backend/tests/db/test_user.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add User model"
```

---

### Task 5: Event model

**Files:**
- Create: `backend/app/db/models/event.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/db/migrations/env.py`
- Create: `backend/tests/db/test_event.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_event.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event  # noqa: F401
from app.db.models.event import Event


def _event_kwargs(**overrides):
    base = dict(
        id="evt_1",
        external_id="eb_12345",
        source="eventbrite",
        title="Jazz Night",
        description="Trio set",
        summary="Doors 20:00",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc),
        venue_name="Mojo Club",
        venue_address="Reeperbahn 1",
        latitude=53.5497,
        longitude=9.9657,
        category="music",
        tags=["jazz", "live"],
        price_min=18.0,
        price_max=24.0,
        is_free=False,
        currency="EUR",
        image_url="https://example.com/img.jpg",
        source_url="https://eventbrite.de/e/12345",
        raw_data={"id": "12345"},
    )
    base.update(overrides)
    return base


def test_event_creation(db_session):
    e = Event(**_event_kwargs())
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    assert e.is_active is True
    assert e.currency == "EUR"
    assert isinstance(e.ingested_at, datetime)


def test_event_unique_external_id_source(db_session):
    db_session.add(Event(**_event_kwargs(id="evt_a")))
    db_session.commit()
    db_session.add(Event(**_event_kwargs(id="evt_b")))  # same (external_id, source)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_event_allows_same_external_id_different_source(db_session):
    db_session.add(Event(**_event_kwargs(id="evt_a", source="eventbrite")))
    db_session.add(Event(**_event_kwargs(id="evt_b", source="ticketmaster")))
    db_session.commit()  # no error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_event.py -v`
Expected: FAIL with `ImportError: cannot import name 'event' from 'app.db.models'`.

- [ ] **Step 3: Write `backend/app/db/models/event.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("external_id", "source", name="uq_event_external_source"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String, nullable=True)
    venue_address: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 4: Update `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.event import Event
from app.db.models.user import User

__all__ = ["Event", "User"]
```

- [ ] **Step 5: Add the import to `backend/app/db/migrations/env.py`**

Add after the existing user model import:
```python
from app.db.models import event as _event_model  # noqa: F401
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_event.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/db/models backend/tests/db/test_event.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add Event model with (external_id, source) uniqueness"
```

---

### Task 6: Feedback model

**Files:**
- Create: `backend/app/db/models/feedback.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/db/migrations/env.py`
- Create: `backend/tests/db/test_feedback.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_feedback.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event, feedback as _feedback, user as _user  # noqa: F401
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.add(Event(
        id="evt_1", external_id="x", source="eventbrite", title="t",
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        category="music", tags=[], is_free=False, source_url="https://x", raw_data={},
    ))
    db_session.commit()


def test_feedback_creation(db_session):
    _seed(db_session)
    fb = Feedback(id="fb_1", user_id="local", event_id="evt_1", sentiment="like", comment="great")
    db_session.add(fb)
    db_session.commit()
    db_session.refresh(fb)
    assert fb.sentiment == "like"
    assert fb.comment == "great"
    assert isinstance(fb.created_at, datetime)
    assert isinstance(fb.updated_at, datetime)


def test_feedback_unique_per_user_event(db_session):
    _seed(db_session)
    db_session.add(Feedback(id="fb_1", user_id="local", event_id="evt_1", sentiment="like"))
    db_session.commit()
    db_session.add(Feedback(id="fb_2", user_id="local", event_id="evt_1", sentiment="dislike"))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_feedback.py -v`
Expected: FAIL with `ImportError: cannot import name 'feedback' from 'app.db.models'`.

- [ ] **Step 3: Write `backend/app/db/models/feedback.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_feedback_user_event"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"), nullable=False)
    sentiment: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 4: Update `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.user import User

__all__ = ["Event", "Feedback", "User"]
```

- [ ] **Step 5: Add the import to `backend/app/db/migrations/env.py`**

```python
from app.db.models import feedback as _feedback_model  # noqa: F401
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_feedback.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/db/models backend/tests/db/test_feedback.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add Feedback model with (user_id, event_id) uniqueness"
```

---

### Task 7: SavedEvent model

**Files:**
- Create: `backend/app/db/models/saved_event.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/db/migrations/env.py`
- Create: `backend/tests/db/test_saved_event.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_saved_event.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event, saved_event as _saved, user as _user  # noqa: F401
from app.db.models.event import Event
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.add(Event(
        id="evt_1", external_id="x", source="eventbrite", title="t",
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        category="music", tags=[], is_free=False, source_url="https://x", raw_data={},
    ))
    db_session.commit()


def test_saved_event_creation(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert isinstance(s.saved_at, datetime)


def test_saved_event_unique_per_user_event(db_session):
    _seed(db_session)
    db_session.add(SavedEvent(id="sav_1", user_id="local", event_id="evt_1"))
    db_session.commit()
    db_session.add(SavedEvent(id="sav_2", user_id="local", event_id="evt_1"))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_saved_event.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `backend/app/db/models/saved_event.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SavedEvent(Base):
    __tablename__ = "saved_events"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_saved_user_event"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"), nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
```

- [ ] **Step 4: Update `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User

__all__ = ["Event", "Feedback", "SavedEvent", "User"]
```

- [ ] **Step 5: Add the import to `backend/app/db/migrations/env.py`**

```python
from app.db.models import saved_event as _saved_event_model  # noqa: F401
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_saved_event.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/db/models backend/tests/db/test_saved_event.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add SavedEvent model"
```

---

### Task 8: ChatMessage model

**Files:**
- Create: `backend/app/db/models/chat_message.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/db/migrations/env.py`
- Create: `backend/tests/db/test_chat_message.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_chat_message.py`**

```python
from datetime import datetime, timezone

from app.db.models import chat_message as _cm, user as _user  # noqa: F401
from app.db.models.chat_message import ChatMessage
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()


def test_chat_message_user_role(db_session):
    _seed(db_session)
    m = ChatMessage(id="msg_1", user_id="local", session_id="sess_a", role="user", content="hi")
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.role == "user"
    assert m.tool_name is None
    assert m.input_tokens is None
    assert m.output_tokens is None
    assert m.estimated_cost_usd is None
    assert isinstance(m.created_at, datetime)


def test_chat_message_assistant_with_token_usage(db_session):
    _seed(db_session)
    m = ChatMessage(
        id="msg_2", user_id="local", session_id="sess_a", role="assistant",
        content="hello", input_tokens=420, output_tokens=88, estimated_cost_usd=0.0012,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.input_tokens == 420
    assert m.output_tokens == 88
    assert m.estimated_cost_usd == 0.0012


def test_chat_message_tool_role(db_session):
    _seed(db_session)
    m = ChatMessage(
        id="msg_3", user_id="local", session_id="sess_a", role="tool",
        content='{"events":[]}', tool_name="search_events",
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.tool_name == "search_events"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_chat_message.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `backend/app/db/models/chat_message.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
```

- [ ] **Step 4: Update `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.chat_message import ChatMessage
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User

__all__ = ["ChatMessage", "Event", "Feedback", "SavedEvent", "User"]
```

- [ ] **Step 5: Add the import to `backend/app/db/migrations/env.py`**

```python
from app.db.models import chat_message as _chat_message_model  # noqa: F401
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_chat_message.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/db/models backend/tests/db/test_chat_message.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add ChatMessage model"
```

---

### Task 9: DigestCache model

**Files:**
- Create: `backend/app/db/models/digest_cache.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/db/migrations/env.py`
- Create: `backend/tests/db/test_digest_cache.py`

- [ ] **Step 1: Write the failing test — `backend/tests/db/test_digest_cache.py`**

```python
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import digest_cache as _dc, user as _user  # noqa: F401
from app.db.models.digest_cache import DigestCache
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()


def test_digest_cache_creation(db_session):
    _seed(db_session)
    d = DigestCache(
        id="dig_1", user_id="local", date=date(2026, 6, 8),
        picks=[{"event_id": "evt_1", "justification": "..."}],
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    assert d.picks == [{"event_id": "evt_1", "justification": "..."}]
    assert isinstance(d.generated_at, datetime)


def test_digest_cache_unique_per_user_date(db_session):
    _seed(db_session)
    db_session.add(DigestCache(id="dig_1", user_id="local", date=date(2026, 6, 8), picks=[]))
    db_session.commit()
    db_session.add(DigestCache(id="dig_2", user_id="local", date=date(2026, 6, 8), picks=[]))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_digest_cache.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `backend/app/db/models/digest_cache.py`**

```python
from datetime import date as date_cls, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DigestCache(Base):
    __tablename__ = "digest_cache"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_digest_user_date"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    date: Mapped[date_cls] = mapped_column(Date, nullable=False)
    picks: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
```

- [ ] **Step 4: Update `backend/app/db/models/__init__.py`**

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.chat_message import ChatMessage
from app.db.models.digest_cache import DigestCache
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User

__all__ = ["ChatMessage", "DigestCache", "Event", "Feedback", "SavedEvent", "User"]
```

- [ ] **Step 5: Add the import to `backend/app/db/migrations/env.py`**

```python
from app.db.models import digest_cache as _digest_cache_model  # noqa: F401
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/db/test_digest_cache.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/db/models backend/tests/db/test_digest_cache.py backend/app/db/migrations/env.py
git commit -m "feat(backend): add DigestCache model"
```

---

## Phase 3 — Initial Alembic migration

### Task 10: Autogenerate and verify the initial migration

**Files:**
- Create: `backend/app/db/migrations/versions/0001_initial.py` (via `alembic revision --autogenerate`)
- Modify: that file's `revision` slug to `0001_initial`

- [ ] **Step 1: Run the autogenerate**

```powershell
cd backend
alembic revision --autogenerate -m "initial"
```
Expected: creates a new file under `app/db/migrations/versions/` whose `upgrade()` creates all six tables (`users`, `events`, `feedback`, `saved_events`, `chat_messages`, `digest_cache`).

- [ ] **Step 2: Rename the generated file to `0001_initial.py`** and set its `revision = "0001_initial"` and `down_revision = None`. (Edit the file: the autogen creates a random hash filename and revision — make it stable.)

- [ ] **Step 3: Apply the migration to a fresh DB**

```powershell
del event_tracker.db -ErrorAction SilentlyContinue
alembic upgrade head
```
Expected: no errors, `event_tracker.db` is created.

- [ ] **Step 4: Verify the schema**

```powershell
python -c "from sqlalchemy import create_engine, inspect; e=create_engine('sqlite:///event_tracker.db'); print(sorted(inspect(e).get_table_names()))"
```
Expected output: `['alembic_version', 'chat_messages', 'digest_cache', 'events', 'feedback', 'saved_events', 'users']`.

- [ ] **Step 5: Clean up the dev DB**

```powershell
del event_tracker.db
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/db/migrations/versions/0001_initial.py
git commit -m "feat(backend): add initial Alembic migration for all six tables"
```

---

## Phase 4 — Pydantic API schemas

All schema tasks follow the same shape: write the failing test that exercises construction and serialization, then write the Pydantic models. Use Pydantic v2 (`BaseModel`, `ConfigDict`, `model_dump`).

### Task 11: Common schemas (`EventCard`, `EventWithContext`, `UserSettings`, `ChatTokenUsage`)

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/common.py`
- Create: `backend/tests/schemas/__init__.py`
- Create: `backend/tests/schemas/test_common.py`

- [ ] **Step 1: Write `backend/tests/schemas/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test — `backend/tests/schemas/test_common.py`**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.common import ChatTokenUsage, EventCard, EventWithContext, UserSettings


def _card_kwargs(**overrides):
    base = dict(
        id="evt_1", title="Jazz", summary="trio",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc),
        end_datetime=None, venue_name="Mojo", venue_address="Reeperbahn 1",
        category="music", tags=["jazz"],
        price_min=18.0, price_max=24.0, is_free=False, currency="EUR",
        image_url="https://x/img.jpg", source_url="https://x/e/1", source="eventbrite",
        is_active=True,
    )
    base.update(overrides)
    return base


def test_event_card_serializes_with_iso_datetimes():
    card = EventCard(**_card_kwargs())
    dumped = card.model_dump(mode="json")
    assert dumped["start_datetime"] == "2026-06-14T20:00:00Z"
    assert dumped["category"] == "music"


def test_event_card_rejects_invalid_category():
    with pytest.raises(ValidationError):
        EventCard(**_card_kwargs(category="nope"))


def test_event_with_context_extends_card():
    ctx = EventWithContext(**_card_kwargs(), user_sentiment="like", user_comment="great", is_saved=True)
    assert ctx.user_sentiment == "like"
    assert ctx.is_saved is True


def test_event_with_context_allows_null_sentiment():
    ctx = EventWithContext(**_card_kwargs(), user_sentiment=None, user_comment=None, is_saved=False)
    assert ctx.user_sentiment is None


def test_user_settings_shape():
    s = UserSettings(
        tool_toggles={"search_events": True},
        llm_provider="openai",
        llm_model="gpt-4o-mini",
    )
    assert s.llm_provider == "openai"


def test_user_settings_rejects_invalid_provider():
    with pytest.raises(ValidationError):
        UserSettings(tool_toggles={}, llm_provider="meta", llm_model=None)


def test_chat_token_usage():
    u = ChatTokenUsage(input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)
    assert u.estimated_cost_usd == 0.001
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/schemas/test_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas'`.

- [ ] **Step 4: Write `backend/app/schemas/__init__.py`** (empty)

- [ ] **Step 5: Write `backend/app/schemas/common.py`**

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_CATEGORIES = frozenset({
    "music", "arts", "food", "sports", "tech",
    "outdoor", "film", "theater", "family", "other",
})

EventCategory = Literal[
    "music", "arts", "food", "sports", "tech",
    "outdoor", "film", "theater", "family", "other",
]
Sentiment = Literal["like", "dislike"]
LLMProvider = Literal["openai", "anthropic"]


class _JsonBase(BaseModel):
    """Base model that serializes datetimes as ISO 8601 with `Z` suffix when UTC."""
    model_config = ConfigDict(ser_json_timedelta="iso8601")


class EventCard(_JsonBase):
    id: str
    title: str
    summary: str | None
    start_datetime: datetime
    end_datetime: datetime | None
    venue_name: str | None
    venue_address: str | None
    category: EventCategory
    tags: list[str] = Field(default_factory=list)
    price_min: float | None
    price_max: float | None
    is_free: bool
    currency: str = "EUR"
    image_url: str | None
    source_url: str
    source: str
    is_active: bool = True


class EventWithContext(EventCard):
    user_sentiment: Sentiment | None = None
    user_comment: str | None = None
    is_saved: bool = False


class UserSettings(_JsonBase):
    tool_toggles: dict[str, bool] = Field(default_factory=dict)
    llm_provider: LLMProvider = "openai"
    llm_model: str | None = None


class ChatTokenUsage(_JsonBase):
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/schemas/test_common.py -v`
Expected: 7 passed.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/schemas backend/tests/schemas
git commit -m "feat(backend): add common Pydantic schemas (EventCard, EventWithContext, UserSettings, ChatTokenUsage)"
```

---

### Task 12: Digest schemas (`DigestPick`, `DigestResponse`)

**Files:**
- Create: `backend/app/schemas/digest.py`
- Create: `backend/tests/schemas/test_digest.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_digest.py`**

```python
from datetime import date, datetime, timezone

from app.schemas.common import EventCard
from app.schemas.digest import DigestPick, DigestResponse


def _card():
    return EventCard(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
    )


def test_digest_pick():
    p = DigestPick(event=_card(), justification="because")
    assert p.justification == "because"


def test_digest_response():
    r = DigestResponse(
        date=date(2026, 6, 8),
        picks=[DigestPick(event=_card(), justification="b")],
        generated_at=datetime(2026, 6, 8, 7, tzinfo=timezone.utc),
        is_cached=True,
    )
    dumped = r.model_dump(mode="json")
    assert dumped["date"] == "2026-06-08"
    assert dumped["is_cached"] is True
    assert len(dumped["picks"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_digest.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/digest.py`**

```python
from datetime import date as date_cls, datetime

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class DigestPick(_JsonBase):
    event: EventCard
    justification: str


class DigestResponse(_JsonBase):
    date: date_cls
    picks: list[DigestPick] = Field(default_factory=list)
    generated_at: datetime
    is_cached: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_digest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/digest.py backend/tests/schemas/test_digest.py
git commit -m "feat(backend): add Digest Pydantic schemas"
```

---

### Task 13: Events feed schema (`EventsFeedResponse`)

**Files:**
- Create: `backend/app/schemas/events.py`
- Create: `backend/tests/schemas/test_events.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_events.py`**

```python
from datetime import datetime, timezone

from app.schemas.common import EventWithContext
from app.schemas.events import EventsFeedResponse


def _ctx():
    return EventWithContext(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
        user_sentiment=None, user_comment=None, is_saved=False,
    )


def test_events_feed_response():
    r = EventsFeedResponse(events=[_ctx()], total=1, page=1, page_size=20)
    assert r.total == 1
    assert r.events[0].id == "e1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/events.py`**

```python
from pydantic import Field

from app.schemas.common import EventWithContext, _JsonBase


class EventsFeedResponse(_JsonBase):
    events: list[EventWithContext] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_events.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/events.py backend/tests/schemas/test_events.py
git commit -m "feat(backend): add EventsFeedResponse schema"
```

---

### Task 14: Feedback schemas (`FeedbackCreate`, `FeedbackResponse`)

**Files:**
- Create: `backend/app/schemas/feedback.py`
- Create: `backend/tests/schemas/test_feedback.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_feedback.py`**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.feedback import FeedbackCreate, FeedbackResponse


def test_feedback_create():
    fc = FeedbackCreate(event_id="e1", sentiment="like", comment="loved it")
    assert fc.sentiment == "like"


def test_feedback_create_rejects_invalid_sentiment():
    with pytest.raises(ValidationError):
        FeedbackCreate(event_id="e1", sentiment="meh", comment=None)


def test_feedback_response():
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    fr = FeedbackResponse(id="fb_1", event_id="e1", sentiment="like", comment=None, created_at=now, updated_at=now)
    dumped = fr.model_dump(mode="json")
    assert dumped["sentiment"] == "like"
    assert dumped["comment"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_feedback.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/feedback.py`**

```python
from datetime import datetime

from app.schemas.common import Sentiment, _JsonBase


class FeedbackCreate(_JsonBase):
    event_id: str
    sentiment: Sentiment
    comment: str | None = None


class FeedbackResponse(_JsonBase):
    id: str
    event_id: str
    sentiment: Sentiment
    comment: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_feedback.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/feedback.py backend/tests/schemas/test_feedback.py
git commit -m "feat(backend): add Feedback Pydantic schemas"
```

---

### Task 15: Calendar schemas (`CalendarEntry`, `CalendarResponse`)

**Files:**
- Create: `backend/app/schemas/calendar.py`
- Create: `backend/tests/schemas/test_calendar.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_calendar.py`**

```python
from datetime import datetime, timezone

from app.schemas.calendar import CalendarEntry, CalendarResponse
from app.schemas.common import EventCard


def _card():
    return EventCard(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
    )


def test_calendar_entry():
    ce = CalendarEntry(id="sav_1", event=_card(), saved_at=datetime(2026, 6, 7, tzinfo=timezone.utc))
    assert ce.event.id == "e1"


def test_calendar_response_default_empty():
    cr = CalendarResponse()
    assert cr.entries == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/calendar.py`**

```python
from datetime import datetime

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class CalendarEntry(_JsonBase):
    id: str
    event: EventCard
    saved_at: datetime


class CalendarResponse(_JsonBase):
    entries: list[CalendarEntry] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_calendar.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/calendar.py backend/tests/schemas/test_calendar.py
git commit -m "feat(backend): add Calendar Pydantic schemas"
```

---

### Task 16: Profile and settings schemas

**Files:**
- Create: `backend/app/schemas/profile.py`
- Create: `backend/tests/schemas/test_profile.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_profile.py`**

```python
from app.schemas.common import UserSettings
from app.schemas.profile import OnboardingRequest, SettingsUpdate, UserProfileResponse, UserProfileUpdate


def test_user_profile_response():
    r = UserProfileResponse(
        city="Hamburg", interest_tags=["music"], about_me=None, taste_summary=None,
        settings=UserSettings(tool_toggles={}, llm_provider="openai", llm_model=None),
    )
    assert r.city == "Hamburg"


def test_user_profile_update_partial():
    u = UserProfileUpdate(interest_tags=["music"])
    assert u.about_me is None  # not set, defaults to None
    dumped = u.model_dump(exclude_unset=True)
    assert dumped == {"interest_tags": ["music"]}


def test_onboarding_request():
    o = OnboardingRequest(interest_tags=["music", "tech"], about_me="hi")
    assert o.interest_tags == ["music", "tech"]


def test_settings_update_partial():
    s = SettingsUpdate(llm_provider="anthropic")
    dumped = s.model_dump(exclude_unset=True)
    assert dumped == {"llm_provider": "anthropic"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/profile.py`**

```python
from pydantic import Field

from app.schemas.common import LLMProvider, UserSettings, _JsonBase


class UserProfileResponse(_JsonBase):
    city: str
    interest_tags: list[str] = Field(default_factory=list)
    about_me: str | None
    taste_summary: str | None
    settings: UserSettings


class UserProfileUpdate(_JsonBase):
    interest_tags: list[str] | None = None
    about_me: str | None = None


class OnboardingRequest(_JsonBase):
    interest_tags: list[str] = Field(default_factory=list)
    about_me: str | None = None


class SettingsUpdate(_JsonBase):
    tool_toggles: dict[str, bool] | None = None
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_profile.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/profile.py backend/tests/schemas/test_profile.py
git commit -m "feat(backend): add profile and settings Pydantic schemas"
```

---

### Task 17: Chat schemas (`ChatRequest`, `ChatChunk` union, `ChatMessageResponse`)

**Files:**
- Create: `backend/app/schemas/chat.py`
- Create: `backend/tests/schemas/test_chat.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_chat.py`**

```python
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.chat import (
    ChatChunk, ChatChunkDone, ChatChunkError, ChatChunkToken, ChatChunkToolEnd, ChatChunkToolStart,
    ChatMessageResponse, ChatRequest,
)
from app.schemas.common import ChatTokenUsage


def test_chat_request():
    r = ChatRequest(message="hi", session_id="sess_1")
    assert r.session_id == "sess_1"


def test_chat_chunk_token():
    c = ChatChunkToken(type="token", content="hi")
    assert c.content == "hi"


def test_chat_chunk_tool_start():
    c = ChatChunkToolStart(type="tool_start", tool_name="search_events")
    assert c.tool_name == "search_events"


def test_chat_chunk_tool_end_status():
    c = ChatChunkToolEnd(type="tool_end", tool_name="search_events", status="ok")
    assert c.status == "ok"


def test_chat_chunk_tool_end_rejects_invalid_status():
    with pytest.raises(ValidationError):
        ChatChunkToolEnd(type="tool_end", tool_name="search_events", status="bad")


def test_chat_chunk_done():
    c = ChatChunkDone(type="done", token_usage=ChatTokenUsage(input_tokens=1, output_tokens=2, estimated_cost_usd=0.001))
    assert c.token_usage.input_tokens == 1


def test_chat_chunk_error():
    c = ChatChunkError(type="error", message="rate limited")
    assert c.message == "rate limited"


def test_chat_chunk_union_discriminator():
    adapter = TypeAdapter(ChatChunk)
    parsed = adapter.validate_python({"type": "token", "content": "hi"})
    assert isinstance(parsed, ChatChunkToken)
    parsed2 = adapter.validate_python({"type": "done", "token_usage": {"input_tokens": 1, "output_tokens": 2, "estimated_cost_usd": 0.001}})
    assert isinstance(parsed2, ChatChunkDone)


def test_chat_message_response():
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    m = ChatMessageResponse(
        id="msg_1", session_id="sess_1", role="assistant", content="hello",
        tool_name=None, token_usage=None, created_at=now,
    )
    assert m.role == "assistant"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_chat.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/chat.py`**

```python
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import Field

from app.schemas.common import ChatTokenUsage, _JsonBase

ChatRole = Literal["user", "assistant", "tool"]
ToolStatus = Literal["ok", "error"]


class ChatRequest(_JsonBase):
    message: str
    session_id: str


class ChatChunkToken(_JsonBase):
    type: Literal["token"]
    content: str


class ChatChunkToolStart(_JsonBase):
    type: Literal["tool_start"]
    tool_name: str


class ChatChunkToolEnd(_JsonBase):
    type: Literal["tool_end"]
    tool_name: str
    status: ToolStatus


class ChatChunkDone(_JsonBase):
    type: Literal["done"]
    token_usage: ChatTokenUsage


class ChatChunkError(_JsonBase):
    type: Literal["error"]
    message: str


ChatChunk = Annotated[
    Union[ChatChunkToken, ChatChunkToolStart, ChatChunkToolEnd, ChatChunkDone, ChatChunkError],
    Field(discriminator="type"),
]


class ChatMessageResponse(_JsonBase):
    id: str
    session_id: str
    role: ChatRole
    content: str
    tool_name: str | None
    token_usage: ChatTokenUsage | None
    created_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_chat.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/chat.py backend/tests/schemas/test_chat.py
git commit -m "feat(backend): add Chat Pydantic schemas with discriminated ChatChunk union"
```

---

### Task 18: Usage rollup schema (`UsageRollupResponse`)

**Files:**
- Create: `backend/app/schemas/usage.py`
- Create: `backend/tests/schemas/test_usage.py`

- [ ] **Step 1: Write the failing test — `backend/tests/schemas/test_usage.py`**

```python
from datetime import date

from app.schemas.common import ChatTokenUsage
from app.schemas.usage import UsageDay, UsageRollupResponse


def test_usage_day():
    d = UsageDay(date=date(2026, 6, 2), input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)
    assert d.estimated_cost_usd == 0.001


def test_usage_rollup_response():
    r = UsageRollupResponse(
        today=ChatTokenUsage(input_tokens=10, output_tokens=20, estimated_cost_usd=0.001),
        last_7_days=[UsageDay(date=date(2026, 6, 2), input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)],
    )
    dumped = r.model_dump(mode="json")
    assert dumped["last_7_days"][0]["date"] == "2026-06-02"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schemas/test_usage.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend/app/schemas/usage.py`**

```python
from datetime import date as date_cls

from pydantic import Field

from app.schemas.common import ChatTokenUsage, _JsonBase


class UsageDay(_JsonBase):
    date: date_cls
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageRollupResponse(_JsonBase):
    today: ChatTokenUsage
    last_7_days: list[UsageDay] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schemas/test_usage.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/usage.py backend/tests/schemas/test_usage.py
git commit -m "feat(backend): add UsageRollupResponse schema"
```

---

## Phase 5 — `NormalizedEvent` ingestion contract

### Task 19: `NormalizedEvent` Pydantic model + validators

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/normalize.py`
- Create: `backend/tests/ingestion/__init__.py`
- Create: `backend/tests/ingestion/test_normalize.py`

- [ ] **Step 1: Write `backend/tests/ingestion/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test — `backend/tests/ingestion/test_normalize.py`**

```python
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.ingestion.normalize import NormalizedEvent

BERLIN = timezone(timedelta(hours=2))


def _kwargs(**overrides):
    base = dict(
        external_id="eb_1", source="eventbrite", title="t",
        description="d", summary="s",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=BERLIN),
        end_datetime=datetime(2026, 6, 14, 23, 0, tzinfo=BERLIN),
        venue_name="v", venue_address="a", latitude=53.5, longitude=9.9,
        category="music", tags=["jazz"],
        price_min=10.0, price_max=20.0, is_free=False, currency="EUR",
        image_url="https://x/i", source_url="https://x/e/1", raw_data={"k": "v"},
    )
    base.update(overrides)
    return base


def test_normalized_event_minimal():
    e = NormalizedEvent(**_kwargs())
    assert e.category == "music"
    assert e.currency == "EUR"


def test_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(start_datetime=datetime(2026, 6, 14, 20, 0)))


def test_rejects_unknown_category():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(category="nope"))


def test_rejects_empty_external_id():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(external_id=""))


def test_rejects_empty_source_url():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(source_url=""))


def test_rejects_price_min_gt_max():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(price_min=30.0, price_max=20.0))


def test_is_free_requires_zero_or_null_prices():
    # is_free=True with non-zero prices → error
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(is_free=True, price_min=10.0, price_max=20.0))
    # is_free=True with None prices → ok
    e = NormalizedEvent(**_kwargs(is_free=True, price_min=None, price_max=None))
    assert e.is_free is True
    # is_free=True with 0 prices → ok
    e2 = NormalizedEvent(**_kwargs(is_free=True, price_min=0.0, price_max=0.0))
    assert e2.is_free is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/ingestion/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `backend/app/ingestion/__init__.py`** (empty)

- [ ] **Step 5: Write `backend/app/ingestion/normalize.py`**

```python
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.common import EventCategory, _JsonBase


class NormalizedEvent(_JsonBase):
    """Canonical event shape produced by every source adapter."""

    external_id: str
    source: str
    title: str
    description: str | None = None
    summary: str | None = None
    start_datetime: datetime
    end_datetime: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    category: EventCategory
    tags: list[str] = Field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    is_free: bool
    currency: str = "EUR"
    image_url: str | None = None
    source_url: str
    raw_data: dict = Field(default_factory=dict)

    @field_validator("external_id", "source_url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def _must_be_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _price_consistency(self) -> "NormalizedEvent":
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise ValueError("price_min must be <= price_max")
        if self.is_free:
            for price in (self.price_min, self.price_max):
                if price is not None and price != 0:
                    raise ValueError("is_free=True requires prices to be 0 or None")
        return self
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/ingestion/test_normalize.py -v`
Expected: 7 passed.

- [ ] **Step 7: Run the entire backend suite to confirm nothing regressed**

Run: `pytest`
Expected: all tests pass (model + schema + ingestion).

- [ ] **Step 8: Commit**

```powershell
git add backend/app/ingestion backend/tests/ingestion
git commit -m "feat(backend): add NormalizedEvent ingestion contract with validators"
```

---

## Phase 6 — Frontend scaffolding

### Task 20: Scaffold Next.js 14 project

**Files (all created by `create-next-app`):**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.mjs`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/app/globals.css`
- Create: `frontend/public/...` (default Next.js assets)
- Create: `frontend/.gitignore`

- [ ] **Step 1: Scaffold from repo root**

```powershell
npx create-next-app@14 frontend --typescript --tailwind --app --import-alias "@/*" --no-eslint --no-src-dir
```
When prompted for options the flags don't cover, accept defaults.

Expected: `frontend/` directory populated, `node_modules/` installed.

- [ ] **Step 2: Verify the dev build works**

```powershell
cd frontend
npm run build
```
Expected: build completes successfully.

- [ ] **Step 3: Add `frontend/node_modules` to root `.gitignore`** if not already covered

Open `.gitignore` at the repo root and add:
```
# Node
node_modules/
.next/
out/
```
(Skip lines already present.)

- [ ] **Step 4: Commit**

```powershell
cd ..
git add frontend .gitignore
git commit -m "chore(frontend): scaffold Next.js 14 app with TypeScript and Tailwind"
```

---

## Phase 7 — TypeScript types

### Task 21: `lib/types.ts` mirroring Pydantic schemas

**Files:**
- Create: `frontend/lib/types.ts`

- [ ] **Step 1: Write `frontend/lib/types.ts`**

```ts
// Source of truth for these shapes is backend/app/schemas/*.py and backend/app/ingestion/normalize.py.
// Keep this file in sync with those modules — the JSON fixtures in fixtures/ exercise both sides.

export type EventCategory =
  | "music" | "arts" | "food" | "sports" | "tech"
  | "outdoor" | "film" | "theater" | "family" | "other";

export type Sentiment = "like" | "dislike";
export type LLMProvider = "openai" | "anthropic";
export type ChatRole = "user" | "assistant" | "tool";
export type ToolStatus = "ok" | "error";

export interface EventCard {
  id: string;
  title: string;
  summary: string | null;
  start_datetime: string;   // ISO 8601
  end_datetime: string | null;
  venue_name: string | null;
  venue_address: string | null;
  category: EventCategory;
  tags: string[];
  price_min: number | null;
  price_max: number | null;
  is_free: boolean;
  currency: string;
  image_url: string | null;
  source_url: string;
  source: string;
  is_active: boolean;
}

export interface EventWithContext extends EventCard {
  user_sentiment: Sentiment | null;
  user_comment: string | null;
  is_saved: boolean;
}

export interface UserSettings {
  tool_toggles: Record<string, boolean>;
  llm_provider: LLMProvider;
  llm_model: string | null;
}

export interface ChatTokenUsage {
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface DigestPick {
  event: EventCard;
  justification: string;
}

export interface DigestResponse {
  date: string;             // ISO date (YYYY-MM-DD)
  picks: DigestPick[];
  generated_at: string;     // ISO 8601
  is_cached: boolean;
}

export interface EventsFeedResponse {
  events: EventWithContext[];
  total: number;
  page: number;
  page_size: number;
}

export interface FeedbackCreate {
  event_id: string;
  sentiment: Sentiment;
  comment: string | null;
}

export interface FeedbackResponse {
  id: string;
  event_id: string;
  sentiment: Sentiment;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarEntry {
  id: string;
  event: EventCard;
  saved_at: string;
}

export interface CalendarResponse {
  entries: CalendarEntry[];
}

export interface UserProfileResponse {
  city: string;
  interest_tags: string[];
  about_me: string | null;
  taste_summary: string | null;
  settings: UserSettings;
}

export interface UserProfileUpdate {
  interest_tags?: string[];
  about_me?: string | null;
}

export interface OnboardingRequest {
  interest_tags: string[];
  about_me: string | null;
}

export interface SettingsUpdate {
  tool_toggles?: Record<string, boolean>;
  llm_provider?: LLMProvider;
  llm_model?: string | null;
}

export interface ChatRequest {
  message: string;
  session_id: string;
}

export type ChatChunk =
  | { type: "token";      content: string }
  | { type: "tool_start"; tool_name: string }
  | { type: "tool_end";   tool_name: string; status: ToolStatus }
  | { type: "done";       token_usage: ChatTokenUsage }
  | { type: "error";      message: string };

export interface ChatMessageResponse {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  tool_name: string | null;
  token_usage: ChatTokenUsage | null;
  created_at: string;
}

export interface UsageDay {
  date: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface UsageRollupResponse {
  today: ChatTokenUsage;
  last_7_days: UsageDay[];
}
```

- [ ] **Step 2: Verify the file type-checks**

```powershell
cd frontend
npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```powershell
cd ..
git add frontend/lib/types.ts
git commit -m "feat(frontend): add TypeScript types mirroring backend schemas"
```

---

## Phase 8 — JSON fixtures + contract test

### Task 22: Create all eight fixture files

**Files:**
- Create: `frontend/fixtures/digest.json`
- Create: `frontend/fixtures/events.json`
- Create: `frontend/fixtures/event-detail.json`
- Create: `frontend/fixtures/calendar.json`
- Create: `frontend/fixtures/profile.json`
- Create: `frontend/fixtures/settings.json`
- Create: `frontend/fixtures/usage.json`
- Create: `frontend/fixtures/chat-stream.json`

The content guidelines from spec §6.4 apply: variety of categories, prices (including `is_free=true` and unknown prices), `user_sentiment` values, at least one `is_active=false` saved entry, real Hamburg venue names.

- [ ] **Step 1: Write `frontend/fixtures/digest.json`**

```json
{
  "date": "2026-06-08",
  "picks": [
    {
      "event": {
        "id": "evt_001",
        "title": "Jazz Night at Mojo Club",
        "summary": "Intimate trio set, doors 20:00",
        "start_datetime": "2026-06-14T20:00:00+02:00",
        "end_datetime": "2026-06-14T23:00:00+02:00",
        "venue_name": "Mojo Club",
        "venue_address": "Reeperbahn 1, 20359 Hamburg",
        "category": "music",
        "tags": ["jazz", "live music", "intimate"],
        "price_min": 18.0,
        "price_max": 24.0,
        "is_free": false,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?w=800",
        "source_url": "https://www.eventbrite.de/e/jazz-night-12345",
        "source": "eventbrite",
        "is_active": true
      },
      "justification": "You consistently liked small intimate jazz venues last month, and this is a trio set at one of your saved spots."
    },
    {
      "event": {
        "id": "evt_002",
        "title": "Open-Air Coding Meetup",
        "summary": "Outdoor hack session at Stadtpark",
        "start_datetime": "2026-06-13T15:00:00+02:00",
        "end_datetime": "2026-06-13T19:00:00+02:00",
        "venue_name": "Hamburger Stadtpark",
        "venue_address": "Otto-Wels-Straße 3, 22303 Hamburg",
        "category": "tech",
        "tags": ["meetup", "outdoor", "coding"],
        "price_min": null,
        "price_max": null,
        "is_free": true,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=800",
        "source_url": "https://meetup.example/hh-code-outside",
        "source": "hamburg_scraper",
        "is_active": true
      },
      "justification": "Combines two stated interests — tech and outdoor — and it's free; matches your bias toward low-commitment weekday events."
    },
    {
      "event": {
        "id": "evt_003",
        "title": "Hamburg Street Food Festival",
        "summary": "Weekend food market in the Schanze",
        "start_datetime": "2026-06-15T11:00:00+02:00",
        "end_datetime": "2026-06-15T22:00:00+02:00",
        "venue_name": "Schanzenviertel",
        "venue_address": "Sternschanze, 20357 Hamburg",
        "category": "food",
        "tags": ["food", "market", "weekend"],
        "price_min": null,
        "price_max": null,
        "is_free": true,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=800",
        "source_url": "https://www.eventbrite.de/e/street-food-67890",
        "source": "eventbrite",
        "is_active": true
      },
      "justification": "Free, casual, in a neighbourhood you've reacted positively to before."
    },
    {
      "event": {
        "id": "evt_004",
        "title": "Kampnagel: Contemporary Dance",
        "summary": "International dance series, ticketed",
        "start_datetime": "2026-06-16T19:30:00+02:00",
        "end_datetime": "2026-06-16T21:00:00+02:00",
        "venue_name": "Kampnagel",
        "venue_address": "Jarrestraße 20, 22303 Hamburg",
        "category": "theater",
        "tags": ["dance", "contemporary"],
        "price_min": 28.0,
        "price_max": 42.0,
        "is_free": false,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1535525153412-5a092d46b07a?w=800",
        "source_url": "https://www.ticketmaster.de/event/kampnagel-dance",
        "source": "ticketmaster",
        "is_active": true
      },
      "justification": "Stretching beyond music since you've mentioned wanting to see more performance art."
    }
  ],
  "generated_at": "2026-06-08T07:42:11+02:00",
  "is_cached": true
}
```

- [ ] **Step 2: Write `frontend/fixtures/events.json`**

```json
{
  "events": [
    {
      "id": "evt_001",
      "title": "Jazz Night at Mojo Club",
      "summary": "Intimate trio set, doors 20:00",
      "start_datetime": "2026-06-14T20:00:00+02:00",
      "end_datetime": "2026-06-14T23:00:00+02:00",
      "venue_name": "Mojo Club",
      "venue_address": "Reeperbahn 1, 20359 Hamburg",
      "category": "music",
      "tags": ["jazz", "live music"],
      "price_min": 18.0,
      "price_max": 24.0,
      "is_free": false,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?w=800",
      "source_url": "https://www.eventbrite.de/e/jazz-night-12345",
      "source": "eventbrite",
      "is_active": true,
      "user_sentiment": "like",
      "user_comment": "loved this venue last time",
      "is_saved": true
    },
    {
      "id": "evt_002",
      "title": "Open-Air Coding Meetup",
      "summary": "Outdoor hack session at Stadtpark",
      "start_datetime": "2026-06-13T15:00:00+02:00",
      "end_datetime": "2026-06-13T19:00:00+02:00",
      "venue_name": "Hamburger Stadtpark",
      "venue_address": "Otto-Wels-Straße 3, 22303 Hamburg",
      "category": "tech",
      "tags": ["meetup", "outdoor"],
      "price_min": null,
      "price_max": null,
      "is_free": true,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=800",
      "source_url": "https://meetup.example/hh-code-outside",
      "source": "hamburg_scraper",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": false
    },
    {
      "id": "evt_003",
      "title": "Hamburg Street Food Festival",
      "summary": "Weekend food market in the Schanze",
      "start_datetime": "2026-06-15T11:00:00+02:00",
      "end_datetime": "2026-06-15T22:00:00+02:00",
      "venue_name": "Schanzenviertel",
      "venue_address": "Sternschanze, 20357 Hamburg",
      "category": "food",
      "tags": ["food", "market"],
      "price_min": null,
      "price_max": null,
      "is_free": true,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=800",
      "source_url": "https://www.eventbrite.de/e/street-food-67890",
      "source": "eventbrite",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": true
    },
    {
      "id": "evt_004",
      "title": "Kampnagel: Contemporary Dance",
      "summary": "International dance series",
      "start_datetime": "2026-06-16T19:30:00+02:00",
      "end_datetime": "2026-06-16T21:00:00+02:00",
      "venue_name": "Kampnagel",
      "venue_address": "Jarrestraße 20, 22303 Hamburg",
      "category": "theater",
      "tags": ["dance"],
      "price_min": 28.0,
      "price_max": 42.0,
      "is_free": false,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1535525153412-5a092d46b07a?w=800",
      "source_url": "https://www.ticketmaster.de/event/kampnagel-dance",
      "source": "ticketmaster",
      "is_active": true,
      "user_sentiment": "dislike",
      "user_comment": "not my thing",
      "is_saved": false
    },
    {
      "id": "evt_005",
      "title": "Elbphilharmonie: Mahler Symphony No. 5",
      "summary": "NDR Elbphilharmonie Orchestra",
      "start_datetime": "2026-06-20T19:30:00+02:00",
      "end_datetime": "2026-06-20T21:30:00+02:00",
      "venue_name": "Elbphilharmonie",
      "venue_address": "Platz der Deutschen Einheit 4, 20457 Hamburg",
      "category": "music",
      "tags": ["classical", "orchestra"],
      "price_min": 35.0,
      "price_max": 120.0,
      "is_free": false,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1465847899084-d164df4dedc6?w=800",
      "source_url": "https://www.ticketmaster.de/event/elbphi-mahler",
      "source": "ticketmaster",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": false
    },
    {
      "id": "evt_006",
      "title": "Sunday Bike Tour: Alster Loop",
      "summary": "Casual group ride, 18 km",
      "start_datetime": "2026-06-21T10:00:00+02:00",
      "end_datetime": "2026-06-21T13:00:00+02:00",
      "venue_name": "Aussenalster",
      "venue_address": "Aussenalster, Hamburg",
      "category": "outdoor",
      "tags": ["cycling", "group"],
      "price_min": null,
      "price_max": null,
      "is_free": true,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1517649763962-0c623066013b?w=800",
      "source_url": "https://meetup.example/alster-bike",
      "source": "hamburg_scraper",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": false
    },
    {
      "id": "evt_007",
      "title": "Indie Film Screening: Sleeping Dogs Lie",
      "summary": "Hamburg Indie Cinema Club",
      "start_datetime": "2026-06-18T20:00:00+02:00",
      "end_datetime": "2026-06-18T22:00:00+02:00",
      "venue_name": "Metropolis Kino",
      "venue_address": "Kleine Theaterstraße 10, 20354 Hamburg",
      "category": "film",
      "tags": ["indie", "screening"],
      "price_min": 9.0,
      "price_max": 9.0,
      "is_free": false,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1489599809505-f2f1bcec19a0?w=800",
      "source_url": "https://meetup.example/metropolis-indie",
      "source": "hamburg_scraper",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": false
    },
    {
      "id": "evt_008",
      "title": "Family Day at Miniatur Wunderland",
      "summary": "Family-friendly afternoon",
      "start_datetime": "2026-06-22T14:00:00+02:00",
      "end_datetime": "2026-06-22T17:00:00+02:00",
      "venue_name": "Miniatur Wunderland",
      "venue_address": "Kehrwieder 2, 20457 Hamburg",
      "category": "family",
      "tags": ["family"],
      "price_min": 12.0,
      "price_max": 20.0,
      "is_free": false,
      "currency": "EUR",
      "image_url": "https://images.unsplash.com/photo-1503455637927-730bce8583c0?w=800",
      "source_url": "https://www.eventbrite.de/e/miniatur-family",
      "source": "eventbrite",
      "is_active": true,
      "user_sentiment": null,
      "user_comment": null,
      "is_saved": false
    }
  ],
  "total": 8,
  "page": 1,
  "page_size": 20
}
```

- [ ] **Step 3: Write `frontend/fixtures/event-detail.json`** — same as `evt_001` from above with `user_sentiment="like"`:

```json
{
  "id": "evt_001",
  "title": "Jazz Night at Mojo Club",
  "summary": "Intimate trio set, doors 20:00",
  "start_datetime": "2026-06-14T20:00:00+02:00",
  "end_datetime": "2026-06-14T23:00:00+02:00",
  "venue_name": "Mojo Club",
  "venue_address": "Reeperbahn 1, 20359 Hamburg",
  "category": "music",
  "tags": ["jazz", "live music", "intimate"],
  "price_min": 18.0,
  "price_max": 24.0,
  "is_free": false,
  "currency": "EUR",
  "image_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?w=800",
  "source_url": "https://www.eventbrite.de/e/jazz-night-12345",
  "source": "eventbrite",
  "is_active": true,
  "user_sentiment": "like",
  "user_comment": "loved this venue last time",
  "is_saved": true
}
```

- [ ] **Step 4: Write `frontend/fixtures/calendar.json`** — include one `is_active=false` entry to exercise gray-out path:

```json
{
  "entries": [
    {
      "id": "sav_001",
      "event": {
        "id": "evt_001",
        "title": "Jazz Night at Mojo Club",
        "summary": "Intimate trio set, doors 20:00",
        "start_datetime": "2026-06-14T20:00:00+02:00",
        "end_datetime": "2026-06-14T23:00:00+02:00",
        "venue_name": "Mojo Club",
        "venue_address": "Reeperbahn 1, 20359 Hamburg",
        "category": "music",
        "tags": ["jazz"],
        "price_min": 18.0,
        "price_max": 24.0,
        "is_free": false,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?w=800",
        "source_url": "https://www.eventbrite.de/e/jazz-night-12345",
        "source": "eventbrite",
        "is_active": true
      },
      "saved_at": "2026-06-07T11:02:00+02:00"
    },
    {
      "id": "sav_002",
      "event": {
        "id": "evt_003",
        "title": "Hamburg Street Food Festival",
        "summary": "Weekend food market in the Schanze",
        "start_datetime": "2026-06-15T11:00:00+02:00",
        "end_datetime": "2026-06-15T22:00:00+02:00",
        "venue_name": "Schanzenviertel",
        "venue_address": "Sternschanze, 20357 Hamburg",
        "category": "food",
        "tags": ["food", "market"],
        "price_min": null,
        "price_max": null,
        "is_free": true,
        "currency": "EUR",
        "image_url": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=800",
        "source_url": "https://www.eventbrite.de/e/street-food-67890",
        "source": "eventbrite",
        "is_active": true
      },
      "saved_at": "2026-06-06T18:30:00+02:00"
    },
    {
      "id": "sav_003",
      "event": {
        "id": "evt_099",
        "title": "Cancelled: Hafenfest Mini-Concert",
        "summary": "Originally scheduled at the Landungsbrücken",
        "start_datetime": "2026-06-05T18:00:00+02:00",
        "end_datetime": "2026-06-05T20:00:00+02:00",
        "venue_name": "Landungsbrücken",
        "venue_address": "Landungsbrücken, 20359 Hamburg",
        "category": "music",
        "tags": ["concert"],
        "price_min": null,
        "price_max": null,
        "is_free": true,
        "currency": "EUR",
        "image_url": null,
        "source_url": "https://meetup.example/hafenfest",
        "source": "hamburg_scraper",
        "is_active": false
      },
      "saved_at": "2026-06-01T09:14:00+02:00"
    }
  ]
}
```

- [ ] **Step 5: Write `frontend/fixtures/profile.json`**

```json
{
  "city": "Hamburg",
  "interest_tags": ["music", "tech", "outdoor", "food"],
  "about_me": "Backend dev, prefer small venues, hate crowds.",
  "taste_summary": "Prefers small intimate venues, dislikes EDM, weekday late-evening OK, neutral on outdoor.",
  "settings": {
    "tool_toggles": {
      "search_events": true,
      "get_recommendations": true,
      "record_feedback": true,
      "save_to_calendar": true,
      "get_calendar": true,
      "get_user_profile": true,
      "update_user_profile": true
    },
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
```

- [ ] **Step 6: Write `frontend/fixtures/settings.json`**

```json
{
  "tool_toggles": {
    "search_events": true,
    "get_recommendations": true,
    "record_feedback": true,
    "save_to_calendar": true,
    "get_calendar": true,
    "get_user_profile": true,
    "update_user_profile": true
  },
  "llm_provider": "openai",
  "llm_model": "gpt-4o-mini"
}
```

- [ ] **Step 7: Write `frontend/fixtures/usage.json`**

```json
{
  "today": { "input_tokens": 1240, "output_tokens": 380, "estimated_cost_usd": 0.0048 },
  "last_7_days": [
    { "date": "2026-06-02", "input_tokens": 980,  "output_tokens": 220, "estimated_cost_usd": 0.0032 },
    { "date": "2026-06-03", "input_tokens": 1100, "output_tokens": 260, "estimated_cost_usd": 0.0038 },
    { "date": "2026-06-04", "input_tokens": 420,  "output_tokens": 90,  "estimated_cost_usd": 0.0013 },
    { "date": "2026-06-05", "input_tokens": 1450, "output_tokens": 410, "estimated_cost_usd": 0.0055 },
    { "date": "2026-06-06", "input_tokens": 880,  "output_tokens": 190, "estimated_cost_usd": 0.0028 },
    { "date": "2026-06-07", "input_tokens": 1320, "output_tokens": 350, "estimated_cost_usd": 0.0046 },
    { "date": "2026-06-08", "input_tokens": 1240, "output_tokens": 380, "estimated_cost_usd": 0.0048 }
  ]
}
```

- [ ] **Step 8: Write `frontend/fixtures/chat-stream.json`**

```json
[
  { "type": "token", "content": "Looking" },
  { "type": "token", "content": " for events" },
  { "type": "token", "content": " that match your taste..." },
  { "type": "tool_start", "tool_name": "search_events" },
  { "type": "tool_end",   "tool_name": "search_events", "status": "ok" },
  { "type": "token", "content": " Found 3 matches:" },
  { "type": "token", "content": " a small jazz set on Friday, an outdoor coding meetup, and a street-food festival." },
  { "type": "done", "token_usage": { "input_tokens": 420, "output_tokens": 88, "estimated_cost_usd": 0.0012 } }
]
```

- [ ] **Step 9: Commit**

```powershell
git add frontend/fixtures
git commit -m "feat(frontend): add JSON fixtures matching backend schemas"
```

---

### Task 23: Contract test — backend validates frontend fixtures

This ensures the frontend fixtures stay in sync with the backend Pydantic schemas. If a Pydantic field is renamed, this test fails and forces an update on both sides.

**Files:**
- Create: `backend/tests/contract/__init__.py`
- Create: `backend/tests/contract/test_fixtures.py`

- [ ] **Step 1: Write `backend/tests/contract/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test — `backend/tests/contract/test_fixtures.py`**

```python
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.schemas.calendar import CalendarResponse
from app.schemas.chat import ChatChunk
from app.schemas.common import EventWithContext, UserSettings
from app.schemas.digest import DigestResponse
from app.schemas.events import EventsFeedResponse
from app.schemas.profile import UserProfileResponse
from app.schemas.usage import UsageRollupResponse

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "fixtures"

FIXTURE_TO_SCHEMA = [
    ("digest.json",        DigestResponse),
    ("events.json",        EventsFeedResponse),
    ("event-detail.json",  EventWithContext),
    ("calendar.json",      CalendarResponse),
    ("profile.json",       UserProfileResponse),
    ("settings.json",      UserSettings),
    ("usage.json",         UsageRollupResponse),
]


@pytest.mark.parametrize("filename,schema", FIXTURE_TO_SCHEMA)
def test_fixture_validates_against_schema(filename, schema):
    path = FIXTURES_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema.model_validate(payload)


def test_chat_stream_fixture_is_valid_chunks():
    path = FIXTURES_DIR / "chat-stream.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    adapter = TypeAdapter(list[ChatChunk])
    chunks = adapter.validate_python(payload)
    # Stream MUST end with exactly one done or error.
    assert chunks[-1].type in {"done", "error"}
    assert sum(1 for c in chunks if c.type in {"done", "error"}) == 1
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/contract/test_fixtures.py -v`
Expected: 8 passed (7 parameterized + 1 stream test).

- [ ] **Step 4: Run the full backend suite**

Run: `pytest`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/contract
git commit -m "test(backend): add contract test validating frontend fixtures against Pydantic schemas"
```

---

## Phase 9 — `lib/api.ts` with mock switching

### Task 24: API client

**Files:**
- Create: `frontend/lib/api.ts`

- [ ] **Step 1: Write `frontend/lib/api.ts`**

```ts
// Single API client used by every page/component. Switches between a real FastAPI
// backend and the JSON fixtures under fixtures/ via NEXT_PUBLIC_MOCK_MODE.
//
// Mutations in mock mode return a plausible response and log to console — they do
// NOT mutate the fixture files.

import type {
  CalendarEntry,
  CalendarResponse,
  ChatChunk,
  ChatRequest,
  DigestResponse,
  EventsFeedResponse,
  EventWithContext,
  FeedbackCreate,
  FeedbackResponse,
  OnboardingRequest,
  SettingsUpdate,
  UsageRollupResponse,
  UserProfileResponse,
  UserProfileUpdate,
  UserSettings,
} from "@/lib/types";

const MOCK = process.env.NEXT_PUBLIC_MOCK_MODE === "true";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "local";

function headers(extra: HeadersInit = {}): HeadersInit {
  return { "Content-Type": "application/json", "X-User-Id": USER_ID, ...extra };
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { ...init, headers: headers(init?.headers) });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status} ${path}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------- Digest ----------

export async function getDigest(): Promise<DigestResponse> {
  if (MOCK) return (await import("@/fixtures/digest.json")).default as DigestResponse;
  return jsonFetch<DigestResponse>("/digest");
}

export async function refreshDigest(): Promise<DigestResponse> {
  if (MOCK) {
    console.info("[mock] POST /digest/refresh");
    return (await import("@/fixtures/digest.json")).default as DigestResponse;
  }
  return jsonFetch<DigestResponse>("/digest/refresh", { method: "POST" });
}

// ---------- Events ----------

export interface EventsQuery {
  page?: number;
  page_size?: number;
  category?: string;
  date_from?: string;
  date_to?: string;
  is_free?: boolean;
  q?: string;
}

export async function getEvents(query: EventsQuery = {}): Promise<EventsFeedResponse> {
  if (MOCK) return (await import("@/fixtures/events.json")).default as EventsFeedResponse;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const qs = params.toString();
  return jsonFetch<EventsFeedResponse>(`/events${qs ? `?${qs}` : ""}`);
}

export async function getEventDetail(id: string): Promise<EventWithContext> {
  if (MOCK) return (await import("@/fixtures/event-detail.json")).default as EventWithContext;
  return jsonFetch<EventWithContext>(`/events/${encodeURIComponent(id)}`);
}

// ---------- Feedback ----------

export async function postFeedback(body: FeedbackCreate): Promise<FeedbackResponse> {
  if (MOCK) {
    console.info("[mock] POST /feedback", body);
    const now = new Date().toISOString();
    return { id: `fb_mock_${Date.now()}`, ...body, created_at: now, updated_at: now };
  }
  return jsonFetch<FeedbackResponse>("/feedback", { method: "POST", body: JSON.stringify(body) });
}

export async function deleteFeedback(eventId: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /feedback/", eventId);
    return;
  }
  await fetch(`${API_URL}/feedback/${encodeURIComponent(eventId)}`, {
    method: "DELETE", headers: headers(),
  });
}

// ---------- Calendar ----------

export async function getCalendar(): Promise<CalendarResponse> {
  if (MOCK) return (await import("@/fixtures/calendar.json")).default as CalendarResponse;
  return jsonFetch<CalendarResponse>("/calendar");
}

export async function saveToCalendar(eventId: string): Promise<CalendarEntry> {
  if (MOCK) {
    console.info("[mock] POST /calendar/", eventId);
    const detail = (await import("@/fixtures/event-detail.json")).default as EventWithContext;
    const { user_sentiment, user_comment, is_saved, ...card } = detail;
    return { id: `sav_mock_${Date.now()}`, event: card, saved_at: new Date().toISOString() };
  }
  return jsonFetch<CalendarEntry>(`/calendar/${encodeURIComponent(eventId)}`, { method: "POST" });
}

export async function removeFromCalendar(eventId: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /calendar/", eventId);
    return;
  }
  await fetch(`${API_URL}/calendar/${encodeURIComponent(eventId)}`, {
    method: "DELETE", headers: headers(),
  });
}

// ---------- Profile & settings ----------

export async function getProfile(): Promise<UserProfileResponse> {
  if (MOCK) return (await import("@/fixtures/profile.json")).default as UserProfileResponse;
  return jsonFetch<UserProfileResponse>("/profile");
}

export async function updateProfile(body: UserProfileUpdate): Promise<UserProfileResponse> {
  if (MOCK) {
    console.info("[mock] PUT /profile", body);
    const current = (await import("@/fixtures/profile.json")).default as UserProfileResponse;
    return { ...current, ...body, interest_tags: body.interest_tags ?? current.interest_tags };
  }
  return jsonFetch<UserProfileResponse>("/profile", { method: "PUT", body: JSON.stringify(body) });
}

export async function postOnboarding(body: OnboardingRequest): Promise<UserProfileResponse> {
  if (MOCK) {
    console.info("[mock] POST /onboarding", body);
    const current = (await import("@/fixtures/profile.json")).default as UserProfileResponse;
    return { ...current, interest_tags: body.interest_tags, about_me: body.about_me };
  }
  return jsonFetch<UserProfileResponse>("/onboarding", { method: "POST", body: JSON.stringify(body) });
}

export async function getSettings(): Promise<UserSettings> {
  if (MOCK) return (await import("@/fixtures/settings.json")).default as UserSettings;
  return jsonFetch<UserSettings>("/settings");
}

export async function updateSettings(body: SettingsUpdate): Promise<UserSettings> {
  if (MOCK) {
    console.info("[mock] PUT /settings", body);
    const current = (await import("@/fixtures/settings.json")).default as UserSettings;
    return {
      tool_toggles: { ...current.tool_toggles, ...(body.tool_toggles ?? {}) },
      llm_provider: body.llm_provider ?? current.llm_provider,
      llm_model: body.llm_model ?? current.llm_model,
    };
  }
  return jsonFetch<UserSettings>("/settings", { method: "PUT", body: JSON.stringify(body) });
}

// ---------- Usage ----------

export async function getUsage(): Promise<UsageRollupResponse> {
  if (MOCK) return (await import("@/fixtures/usage.json")).default as UsageRollupResponse;
  return jsonFetch<UsageRollupResponse>("/usage");
}

// ---------- Chat (streaming) ----------

/**
 * Subscribe to a chat stream. The handler is invoked once per SSE event, in
 * order. In mock mode, the fixture chunks are emitted with ~120ms spacing so
 * the UI can be developed against realistic streaming behaviour.
 */
export async function postChat(req: ChatRequest, onChunk: (chunk: ChatChunk) => void): Promise<void> {
  if (MOCK) {
    const chunks = (await import("@/fixtures/chat-stream.json")).default as ChatChunk[];
    for (const c of chunks) {
      await new Promise((r) => setTimeout(r, 120));
      onChunk(c);
    }
    return;
  }

  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers({ Accept: "text/event-stream" }),
    body: JSON.stringify(req),
  });
  if (!res.ok || !res.body) throw new Error(`Chat stream failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line; each event has `data: <json>` lines.
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const dataLine = part.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onChunk(JSON.parse(dataLine.slice(5).trim()) as ChatChunk);
      } catch {
        // Ignore malformed chunks rather than killing the stream.
      }
    }
  }
}
```

- [ ] **Step 2: Type-check**

```powershell
cd frontend
npx tsc --noEmit
```
Expected: no errors. If `@/fixtures/*.json` imports fail, add `"resolveJsonModule": true` to `tsconfig.json` under `compilerOptions` (Next.js scaffold normally includes it; verify).

- [ ] **Step 3: Smoke test by importing in a page** — edit `frontend/app/page.tsx` to import `getDigest` and assert it doesn't break the build:

```tsx
import { getDigest } from "@/lib/api";

export default async function HomePage() {
  const digest = await getDigest();
  return (
    <main className="p-8">
      <h1 className="text-2xl font-bold mb-4">Event Tracker — Mock Mode</h1>
      <p className="text-sm text-gray-500 mb-4">Digest date: {digest.date} · {digest.picks.length} picks</p>
      <ul className="space-y-2">
        {digest.picks.map((p) => (
          <li key={p.event.id} className="border p-3 rounded">
            <strong>{p.event.title}</strong> — {p.event.venue_name}
            <p className="text-sm text-gray-600 mt-1">{p.justification}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

- [ ] **Step 4: Run the dev server with MOCK on**

Create `frontend/.env.local`:
```
NEXT_PUBLIC_MOCK_MODE=true
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USER_ID=local
```

Run: `npm run dev`
Open http://localhost:3000 — expected: a list of four picks from `digest.json`.

Kill the dev server (`Ctrl+C`).

- [ ] **Step 5: Commit**

```powershell
cd ..
git add frontend/lib/api.ts frontend/app/page.tsx
git commit -m "feat(frontend): add lib/api.ts with mock-mode switching and smoke page"
```

---

## Phase 10 — `.env.example` files

### Task 25: Add example env files for both projects

**Files:**
- Create: `backend/.env.example`
- Create: `frontend/.env.example`

- [ ] **Step 1: Write `backend/.env.example`**

```
# Backend environment template. Copy to backend/.env and adjust.
DATABASE_URL=sqlite:///./event_tracker.db
DEFAULT_USER_ID=local
```

- [ ] **Step 2: Write `frontend/.env.example`**

```
# Frontend environment template. Copy to frontend/.env.local and adjust.
NEXT_PUBLIC_MOCK_MODE=true
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USER_ID=local
```

- [ ] **Step 3: Commit**

```powershell
git add backend/.env.example frontend/.env.example
git commit -m "chore: add .env.example for backend and frontend"
```

---

## Done

After Task 25 the data-format contract is fully landed:

- `cd backend; pytest` runs the full backend suite (DB models, schemas, ingestion, contract).
- `cd frontend; npm run dev` (with `NEXT_PUBLIC_MOCK_MODE=true`) renders the digest fixture end-to-end.
- The frontend can now develop every screen against the JSON fixtures, with no dependency on a running backend.
- The ingestion-pipeline plan can begin against the `NormalizedEvent` contract in `backend/app/ingestion/normalize.py` and the `Event` model in `backend/app/db/models/event.py`.

The contract test in Task 23 protects against drift: any future change to a Pydantic schema field name or type will fail the contract test, forcing matching updates to both fixtures and `lib/types.ts`.
