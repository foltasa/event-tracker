# LLM-Based Event Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-source substring/exact-match category mapping with a unified LLM classifier that treats the provider's category as a hint and uses title + description + venue + tags as signals.

**Architecture:** New module `app.ingestion.categorize` sits between adapter fetch and DB upsert. Each event goes through `refine_category(ev, cache, llm_client)`. A content-hash cache (SQLite table `event_category_cache`) makes each unique event a one-time classification cost. On any LLM failure, the pipeline keeps the scraper's substring-mapped category, so ingestion never breaks. An Alembic migration creates the cache table and backfills all existing events (~15 min one-time).

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, Pydantic v2, LangChain (`langchain_openai.ChatOpenAI` via OpenRouter — same pattern as `app.agent.llm`), pytest.

**Spec:** `docs/specs/2026-07-04-llm-event-categorization-design.md`.

---

## File Structure

**Create:**
- `backend/app/db/models/event_category_cache.py` — SQLAlchemy model for cache table
- `backend/app/ingestion/categorize.py` — `content_hash`, `CategoryCache`, `CategoryDecision`, `build_categorization_llm`, `refine_category`
- `backend/app/ingestion/categorize_prompts.py` — `SYSTEM_PROMPT` constant + `render_user_prompt(event)`
- `backend/app/db/migrations/versions/0006_event_category_cache.py` — schema + backfill migration
- `backend/scripts/reclassify.py` — `--all` / `--sample N` CLI
- `backend/tests/ingestion/test_categorize.py` — unit tests
- `backend/tests/ingestion/test_categorize_prompts.py` — prompt snapshot tests
- `backend/tests/scripts/test_reclassify.py` — CLI tests

**Modify:**
- `backend/app/config.py` — add `categorization_model`, `categorization_timeout_seconds`
- `backend/app/db/models/__init__.py` — register `EventCategoryCache`
- `backend/app/ingestion/scheduler.py` — insert `refine_category` between fetch and upsert
- `backend/tests/ingestion/test_scheduler.py` — pass fake LLM in fixtures

**Do not touch:**
- `backend/app/ingestion/scrapers/theater_hamburg.py:_CATEGORY_MAP` — kept as fallback for LLM failures
- `backend/app/ingestion/eventbrite.py`, `ticketmaster.py`, `scrapers/hamburg.py` — their existing mappings become fallback hints

---

## Task 1: Add categorization settings

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add failing test**

Create `backend/tests/test_config.py` if it doesn't exist, or append to it:

```python
from app.config import Settings


def test_categorization_defaults():
    s = Settings(_env_file=None)
    assert s.categorization_model == "google/gemini-2.0-flash"
    assert s.categorization_timeout_seconds == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_config.py::test_categorization_defaults -v
```
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'categorization_model'`.

- [ ] **Step 3: Add settings**

In `backend/app/config.py`, inside `class Settings`, after the `agent_temperature` line (~line 25):

```python
    # Event categorization LLM (used by ingestion pipeline)
    categorization_model: str = "google/gemini-2.0-flash"
    categorization_timeout_seconds: float = 10.0
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_config.py::test_categorization_defaults -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): add categorization_model + timeout settings"
```

---

## Task 2: SQLAlchemy model for cache table

**Files:**
- Create: `backend/app/db/models/event_category_cache.py`
- Modify: `backend/app/db/models/__init__.py`
- Test: `backend/tests/db/test_event_category_cache.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/db/test_event_category_cache.py`:

```python
from datetime import datetime

from app.db.models.event_category_cache import EventCategoryCache


def test_insert_and_query(db_session):
    row = EventCategoryCache(
        content_hash="deadbeef",
        category="theater",
        model="google/gemini-2.0-flash",
    )
    db_session.add(row)
    db_session.commit()

    fetched = (
        db_session.query(EventCategoryCache)
        .filter_by(content_hash="deadbeef")
        .one()
    )
    assert fetched.category == "theater"
    assert fetched.model == "google/gemini-2.0-flash"
    assert isinstance(fetched.created_at, datetime)


def test_content_hash_is_primary_key(db_session):
    db_session.add(EventCategoryCache(
        content_hash="h1", category="music", model="m1",
    ))
    db_session.commit()

    # Second insert with same hash should raise IntegrityError on commit
    import pytest
    from sqlalchemy.exc import IntegrityError
    db_session.add(EventCategoryCache(
        content_hash="h1", category="theater", model="m2",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unknown_is_allowed(db_session):
    """Cache stores literal 'unknown' when LLM cannot decide."""
    db_session.add(EventCategoryCache(
        content_hash="h_unknown", category="unknown", model="m",
    ))
    db_session.commit()
    fetched = db_session.query(EventCategoryCache).filter_by(content_hash="h_unknown").one()
    assert fetched.category == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/db/test_event_category_cache.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.models.event_category_cache'`.

- [ ] **Step 3: Create the model**

Create `backend/app/db/models/event_category_cache.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class EventCategoryCache(Base):
    """LLM-classified category, keyed by content-hash of the event's semantic
    fields (title, description, venue, tags, provider-hint). Rows survive
    across ingestion runs so each unique event is classified exactly once."""

    __tablename__ = "event_category_cache"

    content_hash = Column(String, primary_key=True)
    category = Column(String, nullable=False)
    model = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Register in models package**

Read `backend/app/db/models/__init__.py`. Add:

```python
from app.db.models.event_category_cache import EventCategoryCache  # noqa: F401
```

next to the other model imports. This ensures `Base.metadata` sees the table so `create_all` in the test fixture creates it.

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/db/test_event_category_cache.py -v
```
Expected: all three tests PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/db/models/event_category_cache.py backend/app/db/models/__init__.py backend/tests/db/test_event_category_cache.py
git commit -m "feat(db): add event_category_cache model"
```

---

## Task 3: `content_hash` pure function

**Files:**
- Create: `backend/app/ingestion/categorize.py` (partial — only `content_hash`)
- Test: `backend/tests/ingestion/test_categorize.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ingestion/test_categorize.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ingestion.categorize import content_hash
from app.ingestion.normalize import NormalizedEvent

_BERLIN = ZoneInfo("Europe/Berlin")


def _ev(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="ev1",
        source="test",
        title="Title",
        description="Some description",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=_BERLIN),
        venue_name="Venue X",
        category="music",
        tags=["a", "b"],
        is_free=False,
        source_url="https://example.com/ev1",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_hash_is_stable_across_calls():
    a = content_hash(_ev())
    b = content_hash(_ev())
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_ignores_non_semantic_fields():
    """external_id, start_datetime, price, image_url must not affect hash."""
    a = content_hash(_ev())
    b = content_hash(_ev(
        external_id="ev1_other",
        start_datetime=datetime(2027, 1, 1, tzinfo=_BERLIN),
        price_min=99.0,
        price_max=199.0,
        image_url="https://cdn.example.com/x.jpg",
        source_url="https://example.com/other",
    ))
    assert a == b


def test_hash_changes_with_title():
    assert content_hash(_ev(title="A")) != content_hash(_ev(title="B"))


def test_hash_changes_with_description():
    assert content_hash(_ev(description="one")) != content_hash(_ev(description="two"))


def test_hash_changes_with_venue():
    assert content_hash(_ev(venue_name="Elbphilharmonie")) != content_hash(_ev(venue_name="Ohnsorg-Theater"))


def test_hash_changes_with_provider_category_hint():
    assert content_hash(_ev(category="music")) != content_hash(_ev(category="theater"))


def test_hash_ignores_tag_order():
    assert content_hash(_ev(tags=["a", "b"])) == content_hash(_ev(tags=["b", "a"]))


def test_hash_strips_html_from_description():
    """Provider descriptions come pre-stripped in the scraper, but if raw
    HTML sneaks in the hash should not flip on formatting changes."""
    plain = content_hash(_ev(description="Hello world"))
    html = content_hash(_ev(description="<p>Hello world</p>"))
    assert plain == html
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize.py -v
```
Expected: all FAIL with `ModuleNotFoundError: No module named 'app.ingestion.categorize'`.

- [ ] **Step 3: Implement `content_hash`**

Create `backend/app/ingestion/categorize.py`:

```python
"""LLM-based event categorization with content-hash caching.

Runs between adapter fetch and DB upsert. Treats the scraper's substring-
mapped category as a hint, not authority. Cache keyed on the hash of the
event's semantic fields (title, description, venue, tags, provider hint)
so each unique event is classified exactly once across ingestion runs."""
import hashlib

from bs4 import BeautifulSoup

from app.ingestion.normalize import NormalizedEvent


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def content_hash(event: NormalizedEvent) -> str:
    """Return a stable sha256 hex over the event's semantic identity.

    Fields included: title, description (HTML-stripped), venue_name, tags
    (order-independent), and event.category (the provider's hint). Anything
    that can change without affecting classification — datetime, price,
    external_id, source_url, image_url — is excluded so re-fetches of the
    same event hit the cache."""
    parts = [
        event.title or "",
        _strip_html(event.description),
        event.venue_name or "",
        "|".join(sorted(event.tags)),
        event.category,
    ]
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize.py backend/tests/ingestion/test_categorize.py
git commit -m "feat(categorize): content_hash for cache keying"
```

---

## Task 4: `CategoryDecision` Pydantic schema

**Files:**
- Modify: `backend/app/ingestion/categorize.py`
- Modify: `backend/tests/ingestion/test_categorize.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_categorize.py`:

```python
import pytest
from pydantic import ValidationError

from app.ingestion.categorize import CategoryDecision


def test_category_decision_accepts_all_enum_values():
    for cat in ["music", "arts", "food", "sports", "tech", "outdoor", "film", "theater", "family", "other"]:
        d = CategoryDecision(category=cat)
        assert d.category == cat


def test_category_decision_accepts_unknown():
    d = CategoryDecision(category="unknown")
    assert d.category == "unknown"


def test_category_decision_rejects_invalid():
    with pytest.raises(ValidationError):
        CategoryDecision(category="music_theater")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize.py -k category_decision -v
```
Expected: FAIL with `ImportError: cannot import name 'CategoryDecision'`.

- [ ] **Step 3: Add `CategoryDecision`**

Append to `backend/app/ingestion/categorize.py`:

```python
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import EventCategory


class CategoryDecision(BaseModel):
    """LLM's classification result. `unknown` means the model was not
    confident enough to pick one of the enum values."""

    category: EventCategory | Literal["unknown"]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize.py -k category_decision -v
```
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize.py backend/tests/ingestion/test_categorize.py
git commit -m "feat(categorize): CategoryDecision schema (enum | 'unknown')"
```

---

## Task 5: Categorization prompts

**Files:**
- Create: `backend/app/ingestion/categorize_prompts.py`
- Test: `backend/tests/ingestion/test_categorize_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ingestion/test_categorize_prompts.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ingestion.categorize_prompts import SYSTEM_PROMPT, render_user_prompt
from app.ingestion.normalize import NormalizedEvent

_BERLIN = ZoneInfo("Europe/Berlin")


def _ev(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="ev1",
        source="theater_hamburg",
        title="The 27 Club",
        description="A Tribute to Jimi Hendrix, Amy Winehouse, Janis Joplin...",
        start_datetime=datetime(2026, 7, 4, 20, 0, tzinfo=_BERLIN),
        venue_name="St. Pauli Theater",
        category="music",
        tags=["weitere konzerte"],
        is_free=False,
        source_url="https://example.com/the-27-club",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_system_prompt_lists_all_categories():
    for cat in ("music", "arts", "theater", "film", "family", "food", "sports", "tech", "outdoor", "other"):
        assert cat in SYSTEM_PROMPT
    assert "unknown" in SYSTEM_PROMPT


def test_system_prompt_distinguishes_theater_from_music():
    """Should explicitly cover tribute shows / musicals as theater."""
    lowered = SYSTEM_PROMPT.lower()
    assert "musical" in lowered or "tribute" in lowered
    assert "theater" in lowered
    assert "konzert" in lowered or "concert" in lowered


def test_render_user_prompt_includes_all_signals():
    prompt = render_user_prompt(_ev())
    assert "The 27 Club" in prompt
    assert "St. Pauli Theater" in prompt
    assert "weitere konzerte" in prompt
    assert "theater_hamburg" in prompt
    # Provider hint appears verbatim
    assert "music" in prompt


def test_render_user_prompt_handles_missing_optional_fields():
    prompt = render_user_prompt(_ev(description=None, venue_name=None, tags=[]))
    assert "The 27 Club" in prompt
    # No exception, no "None" string leaked
    assert "None" not in prompt


def test_render_user_prompt_truncates_long_description():
    long_desc = "x" * 5000
    prompt = render_user_prompt(_ev(description=long_desc))
    # Body of prompt shouldn't contain the full 5000-char blob
    assert len(prompt) < 3000
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize_prompts.py -v
```
Expected: all FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement prompts**

Create `backend/app/ingestion/categorize_prompts.py`:

```python
"""System and user prompts for the LLM categorization step.

Held separate from `app.agent.prompts` because these prompts have a
different lifecycle (ingestion, not user-facing agent) and audience
(deterministic classifier, not conversational assistant)."""
from app.ingestion.normalize import NormalizedEvent

_MAX_DESCRIPTION_CHARS = 800

SYSTEM_PROMPT = """You classify cultural events into exactly one of these categories:

- music: concerts, DJ sets, classical performances in concert halls, opera performances
- theater: plays, musicals, tribute shows, cabaret, comedy shows, kabarett — including musical/tribute formats when they run as multi-week series in theater venues (e.g. a "Tribute to Jimi Hendrix" show at a Broadway-style theater is theater, not music)
- arts: exhibitions, ballet, contemporary dance, literary readings (Lesung)
- film: cinema screenings, film festivals
- family: children's events, family-oriented programming
- food: culinary events, tastings, food festivals
- sports: sports matches and tournaments
- tech: tech conferences, hackathons, meetups
- outdoor: outdoor recreation, nature events, hiking, park festivals
- other: anything that clearly does not fit the above

If you cannot confidently pick one, return "unknown".

Signals to weigh:
1. Venue name is a strong signal. Ohnsorg-Theater, St. Pauli Theater, Thalia, Ernst-Deutsch-Theater, Komödie Winterhuder Fährhaus, Centralkomitee → theater programming. Elbphilharmonie, Laeiszhalle, Barclays Arena → primarily music but not exclusively (they also host readings, ballet, etc.).
2. Title and description carry the actual content. A "Klavierabend" in a theater venue is still music. A tribute show with 20+ consecutive performances in a theater venue is theater.
3. Provider tags and hints are noisy — treat them as weak evidence. Provider tags like "weitere konzerte" are frequently applied to non-concert theater events.
4. Multi-week runs (30+ consecutive shows) strongly indicate theater rather than concert.

Return only the category value via structured output. No prose."""


def render_user_prompt(event: NormalizedEvent) -> str:
    """Format one event's signals for the user turn of the classification prompt."""
    description = (event.description or "").strip()
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS].rstrip() + "…"

    tags_line = ", ".join(event.tags) if event.tags else "(none)"
    venue_line = event.venue_name or "(unknown)"
    description_line = description or "(none)"

    return (
        f"Title: {event.title}\n"
        f"Description: {description_line}\n"
        f"Venue: {venue_line}\n"
        f"Provider tags: {tags_line}\n"
        f"Source: {event.source}\n"
        f"Provider's suggested category: {event.category}\n"
        f"\n"
        f"Classify this event."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize_prompts.py -v
```
Expected: all five tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize_prompts.py backend/tests/ingestion/test_categorize_prompts.py
git commit -m "feat(categorize): system + user prompts for classifier"
```

---

## Task 6: `CategoryCache` (session-backed read/write)

**Files:**
- Modify: `backend/app/ingestion/categorize.py`
- Modify: `backend/tests/ingestion/test_categorize.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_categorize.py`:

```python
from app.ingestion.categorize import CategoryCache


def test_cache_miss_returns_none(db_session):
    cache = CategoryCache(db_session, model_name="google/gemini-2.0-flash")
    assert cache.get("nonexistent") is None


def test_cache_write_then_read(db_session):
    cache = CategoryCache(db_session, model_name="google/gemini-2.0-flash")
    cache.set("hash123", "theater")
    db_session.commit()
    assert cache.get("hash123") == "theater"


def test_cache_set_is_idempotent(db_session):
    """Second write with same hash is a no-op (INSERT OR IGNORE semantics)."""
    cache = CategoryCache(db_session, model_name="m")
    cache.set("h", "theater")
    db_session.commit()
    cache.set("h", "music")  # should not raise, should not overwrite
    db_session.commit()
    assert cache.get("h") == "theater"


def test_cache_stores_unknown(db_session):
    cache = CategoryCache(db_session, model_name="m")
    cache.set("h_unk", "unknown")
    db_session.commit()
    assert cache.get("h_unk") == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize.py -k cache -v
```
Expected: FAIL with `ImportError: cannot import name 'CategoryCache'`.

- [ ] **Step 3: Implement `CategoryCache`**

Append to `backend/app/ingestion/categorize.py`:

```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.event_category_cache import EventCategoryCache


class CategoryCache:
    """Thin wrapper over `event_category_cache` for get/set-by-hash access.

    Uses SQLite's INSERT OR IGNORE so concurrent runs / retries never fight
    over the same key. Does not commit — caller controls transaction."""

    def __init__(self, session: Session, model_name: str):
        self._session = session
        self._model_name = model_name

    def get(self, content_hash: str) -> str | None:
        row = (
            self._session.query(EventCategoryCache)
            .filter_by(content_hash=content_hash)
            .one_or_none()
        )
        return row.category if row else None

    def set(self, content_hash: str, category: str) -> None:
        stmt = sqlite_insert(EventCategoryCache).values(
            content_hash=content_hash,
            category=category,
            model=self._model_name,
        ).on_conflict_do_nothing(index_elements=["content_hash"])
        self._session.execute(stmt)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize.py -k cache -v
```
Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize.py backend/tests/ingestion/test_categorize.py
git commit -m "feat(categorize): CategoryCache with INSERT OR IGNORE semantics"
```

---

## Task 7: `refine_category` with fake LLM

**Files:**
- Modify: `backend/app/ingestion/categorize.py`
- Modify: `backend/tests/ingestion/test_categorize.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_categorize.py`:

```python
from typing import Protocol
from unittest.mock import MagicMock

from app.ingestion.categorize import CategoryDecision, LLMClassifier, refine_category


class _FakeClassifier:
    """Test double that returns preconfigured decisions or raises."""

    def __init__(self, decisions=None, exception=None, invalid=False):
        self.decisions = decisions or []
        self.exception = exception
        self.invalid = invalid
        self.calls = []

    def classify(self, event) -> CategoryDecision:
        self.calls.append(event.title)
        if self.exception:
            raise self.exception
        if self.invalid:
            # Simulate what happens when structured output validation succeeds
            # but the caller decides the payload is unusable — we raise here.
            raise ValueError("invalid enum value")
        if not self.decisions:
            raise AssertionError("Fake had no decision configured")
        return self.decisions.pop(0)


def test_refine_cache_miss_calls_llm_and_writes_cache(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(decisions=[CategoryDecision(category="theater")])

    result = refine_category(ev, cache, llm)

    assert result == "theater"
    assert len(llm.calls) == 1
    db_session.commit()
    assert cache.get(content_hash(ev)) == "theater"


def test_refine_cache_hit_skips_llm(db_session):
    ev = _ev()
    cache = CategoryCache(db_session, model_name="m")
    cache.set(content_hash(ev), "arts")
    db_session.commit()
    llm = _FakeClassifier()  # no decisions configured

    result = refine_category(ev, cache, llm)

    assert result == "arts"
    assert llm.calls == []  # LLM was not called


def test_refine_llm_error_falls_back_to_provider_hint(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(exception=RuntimeError("openrouter down"))

    result = refine_category(ev, cache, llm)

    assert result == "music"  # fallback to event.category
    db_session.commit()
    # No cache write on error — next run should retry
    assert cache.get(content_hash(ev)) is None


def test_refine_llm_unknown_falls_back_but_caches(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(decisions=[CategoryDecision(category="unknown")])

    result = refine_category(ev, cache, llm)

    assert result == "music"  # fallback to event.category
    db_session.commit()
    # Cache write with 'unknown' sentinel — avoids re-asking a model that already said "unsure"
    assert cache.get(content_hash(ev)) == "unknown"


def test_refine_unknown_cache_hit_still_uses_provider_hint(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    cache.set(content_hash(ev), "unknown")
    db_session.commit()
    llm = _FakeClassifier()  # not called

    result = refine_category(ev, cache, llm)

    assert result == "music"  # cached 'unknown' still resolves to event.category
    assert llm.calls == []


def test_refine_llm_invalid_response_falls_back(db_session):
    ev = _ev()
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(invalid=True)

    result = refine_category(ev, cache, llm)

    assert result == "music"
    db_session.commit()
    assert cache.get(content_hash(ev)) is None  # invalid = same as error, no cache write
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize.py -k refine -v
```
Expected: FAIL with `ImportError: cannot import name 'refine_category'` (or `LLMClassifier`).

- [ ] **Step 3: Implement `refine_category` + `LLMClassifier` protocol**

Append to `backend/app/ingestion/categorize.py`:

```python
import logging
from typing import Protocol

from app.schemas.common import EventCategory

logger = logging.getLogger(__name__)


class LLMClassifier(Protocol):
    """Structural type for the categorization LLM. Any object with a
    `classify(event) -> CategoryDecision` method satisfies this, including
    real LangChain wrappers and test doubles."""

    def classify(self, event: NormalizedEvent) -> CategoryDecision: ...


def refine_category(
    event: NormalizedEvent,
    cache: CategoryCache,
    classifier: LLMClassifier,
) -> EventCategory:
    """Return the final category for `event`.

    Contract:
    - Cache hit with a valid category → return it directly.
    - Cache hit with 'unknown' → return `event.category` (provider hint).
    - Cache miss → call the classifier.
      - success with valid enum → cache + return.
      - success with 'unknown' → cache 'unknown' + return `event.category`.
      - any exception → return `event.category`, do NOT cache.
    """
    hash_ = content_hash(event)
    cached = cache.get(hash_)
    if cached is not None:
        if cached == "unknown":
            return event.category
        return cached  # type: ignore[return-value]

    try:
        decision = classifier.classify(event)
    except Exception:  # noqa: BLE001 — defensive: any classifier failure falls back
        logger.warning(
            "categorize: classifier failed for '%s' — using provider hint '%s'",
            event.title, event.category, exc_info=True,
        )
        return event.category

    if decision.category == "unknown":
        cache.set(hash_, "unknown")
        return event.category

    cache.set(hash_, decision.category)
    return decision.category
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize.py -v
```
Expected: ALL tests in the file PASS (7 hash + 3 decision + 4 cache + 6 refine = 20 tests).

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize.py backend/tests/ingestion/test_categorize.py
git commit -m "feat(categorize): refine_category with cache-then-LLM flow"
```

---

## Task 8: LangChain-backed `LLMClassifier` implementation

**Files:**
- Modify: `backend/app/ingestion/categorize.py`
- Modify: `backend/tests/ingestion/test_categorize.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_categorize.py`:

```python
from unittest.mock import MagicMock

from app.ingestion.categorize import LangchainClassifier, build_categorization_llm


def test_langchain_classifier_calls_structured_llm_and_returns_decision():
    """Structured output invocation → CategoryDecision passthrough."""
    fake_structured = MagicMock()
    fake_structured.invoke.return_value = CategoryDecision(category="theater")

    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured

    classifier = LangchainClassifier(llm=fake_llm)
    result = classifier.classify(_ev())

    assert isinstance(result, CategoryDecision)
    assert result.category == "theater"
    # with_structured_output was called with CategoryDecision schema
    fake_llm.with_structured_output.assert_called_once_with(CategoryDecision)
    # invoke was called with messages that include the system + user prompts
    invoke_arg = fake_structured.invoke.call_args[0][0]
    assert isinstance(invoke_arg, list)
    assert len(invoke_arg) == 2  # system + user
    assert "classify" in invoke_arg[0].content.lower() or "categor" in invoke_arg[0].content.lower()
    assert _ev().title in invoke_arg[1].content


def test_build_categorization_llm_uses_settings(monkeypatch):
    """Factory should read categorization_model and use OpenRouter base URL."""
    from app.ingestion import categorize as cat_module

    captured = {}
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cat_module, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(cat_module.settings, "categorization_model", "test/model")
    monkeypatch.setattr(cat_module.settings, "categorization_timeout_seconds", 7.5)
    monkeypatch.setattr(cat_module.settings, "openrouter_api_key", "sk-test")

    build_categorization_llm()

    assert captured["model"] == "test/model"
    assert captured["api_key"] == "sk-test"
    assert captured["temperature"] == 0
    assert captured["timeout"] == 7.5
    assert "openrouter.ai" in captured["base_url"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_categorize.py -k "langchain or build_categorization" -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `LangchainClassifier` + `build_categorization_llm`**

Append to `backend/app/ingestion/categorize.py`:

```python
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.ingestion.categorize_prompts import SYSTEM_PROMPT, render_user_prompt


def build_categorization_llm() -> ChatOpenAI:
    """Configured LangChain client for the categorization LLM.

    Reuses OpenRouter (same pattern as `app.agent.llm.build_llm`) so we
    don't add a new provider. Temperature=0 for reproducibility; timeout
    keeps the ingestion loop bounded per event."""
    return ChatOpenAI(
        model=settings.categorization_model,
        api_key=settings.openrouter_api_key or "missing",
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        timeout=settings.categorization_timeout_seconds,
        max_retries=2,
    )


class LangchainClassifier:
    """Concrete `LLMClassifier` backed by a LangChain chat model with
    structured output. Constructed once per ingestion run; safe to reuse."""

    def __init__(self, llm: ChatOpenAI | None = None):
        base = llm if llm is not None else build_categorization_llm()
        self._structured = base.with_structured_output(CategoryDecision)

    def classify(self, event: NormalizedEvent) -> CategoryDecision:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=render_user_prompt(event)),
        ]
        return self._structured.invoke(messages)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/ingestion/test_categorize.py -v
```
Expected: all tests still PASS (previous 20 + 2 new = 22).

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/categorize.py backend/tests/ingestion/test_categorize.py
git commit -m "feat(categorize): LangchainClassifier + build_categorization_llm"
```

---

## Task 9: Scheduler integration

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
from app.ingestion.categorize import CategoryDecision
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache


class _FixedClassifier:
    """Test classifier that always returns the same decision."""
    def __init__(self, category="theater"):
        self._category = category
        self.calls = 0

    def classify(self, event):
        self.calls += 1
        return CategoryDecision(category=self._category)


def test_ingestion_overrides_category_via_llm(db_session):
    """Provider hint is 'music' but classifier says 'theater'.
    The row that lands in the DB should have category='theater'."""
    classifier = _FixedClassifier(category="theater")

    run_ingestion(
        adapters=[_OkAdapter()],
        session=db_session,
        classifier=classifier,
    )
    db_session.commit()

    row = db_session.query(Event).filter_by(external_id="ok_1").one()
    assert row.category == "theater"
    assert classifier.calls == 1


def test_ingestion_second_run_hits_cache(db_session):
    classifier = _FixedClassifier(category="theater")

    # First run: LLM called, cache populated
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=classifier)
    db_session.commit()
    assert classifier.calls == 1
    assert db_session.query(EventCategoryCache).count() == 1

    # Second run: same event, cache hit, LLM not called
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=classifier)
    db_session.commit()
    assert classifier.calls == 1  # still 1


def test_ingestion_llm_failure_uses_provider_category(db_session):
    class _BrokenClassifier:
        def classify(self, event):
            raise RuntimeError("openrouter timeout")

    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=_BrokenClassifier())
    db_session.commit()

    row = db_session.query(Event).filter_by(external_id="ok_1").one()
    assert row.category == "music"  # _ev() provider hint
    assert db_session.query(EventCategoryCache).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/ingestion/test_scheduler.py -k "override_category or hits_cache or llm_failure" -v
```
Expected: FAIL — either the tests can't be collected (unknown `classifier` kwarg) or they fail because `run_ingestion` doesn't touch categories.

- [ ] **Step 3: Modify `run_ingestion` to accept and use the classifier**

Read the current `backend/app/ingestion/scheduler.py`. Change `run_ingestion` to:

```python
def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
    classifier: LLMClassifier | None = None,
) -> UpsertReport:
    """Fetch all sources, refine each event's category via LLM, upsert to DB,
    deactivate past events."""
    own_wiki_client = adapters is None
    wiki_client = httpx.Client(timeout=15) if own_wiki_client else None
    if adapters is None:
        adapters = _default_adapters(wiki_client=wiki_client)

    own_session = session is None
    if own_session:
        run_migrations()
        session = SessionLocal()

    if classifier is None:
        classifier = LangchainClassifier()

    try:
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events = []
        for adapter in adapters:
            try:
                batch: list[NormalizedEvent] = []
                for ev in adapter.fetch():
                    ev.category = refine_category(ev, cache, classifier)
                    batch.append(ev)
                all_events.extend(batch)
                logger.info("%s: fetched %d events", adapter.name, len(batch))
            except Exception:
                logger.exception("%s: fetch failed, skipping", adapter.name)

        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        dedup_events(session)
        embed_new_events(session)

        if own_session:
            session.commit()

        logger.info(
            "Ingestion complete — inserted=%d updated=%d skipped=%d",
            report.inserted, report.updated, report.skipped,
        )
        return report
    except Exception:
        if own_session:
            session.rollback()
        logger.exception("run_ingestion failed, rolled back")
        raise
    finally:
        if own_session:
            session.close()
        if own_wiki_client and wiki_client is not None:
            wiki_client.close()
```

Add these imports at the top of the file:

```python
from app.config import settings
from app.ingestion.categorize import (
    CategoryCache,
    LangchainClassifier,
    LLMClassifier,
    refine_category,
)
from app.ingestion.normalize import NormalizedEvent
```

Note: the previous adapter loop calculated `batch = list(adapter.fetch())` then logged the count. The new form is stream-based (refines per event), and the count log is coarser. If test `test_all_adapters_fail_returns_empty_report` breaks, keep the try/except at adapter granularity and log after the inner loop with `len(all_events)` before the loop / after.

- [ ] **Step 4: Run new tests to verify they pass**

```
pytest tests/ingestion/test_scheduler.py -v
```
Expected: all tests PASS, including the pre-existing ones. If pre-existing tests fail because they now need a `classifier=` argument, use a fixture that provides a fake:

Add to the top of `backend/tests/ingestion/test_scheduler.py`:

```python
@pytest.fixture
def fake_classifier():
    """Default classifier for tests that don't care about categorization."""
    class _Passthrough:
        def classify(self, event):
            return CategoryDecision(category=event.category)
    return _Passthrough()
```

Then update existing tests to pass `classifier=fake_classifier` where needed. Example:

```python
def test_inserts_events(db_session, fake_classifier):
    report = run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)
    assert report.inserted == 1
```

Repeat for every pre-existing `run_ingestion` call in the file.

- [ ] **Step 5: Run full ingestion test file**

```
pytest tests/ingestion/test_scheduler.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): refine event category via LLM classifier"
```

---

## Task 10: Alembic migration (schema + backfill)

**Files:**
- Create: `backend/app/db/migrations/versions/0006_event_category_cache.py`
- Test: `backend/tests/db/test_migration_0006.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/db/test_migration_0006.py`:

```python
"""Focused test for the backfill helper. The Alembic migration itself is
kept a thin wrapper around `backfill_categories(session, classifier)` so we
can test the data logic without spinning up Alembic's runner."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db.migrations.versions.migration_0006_helpers import backfill_categories
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision

_BERLIN = ZoneInfo("Europe/Berlin")


class _FixedClassifier:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0

    def classify(self, event):
        self.calls += 1
        cat = self.mapping.get(event.title, "unknown")
        return CategoryDecision(category=cat)


def _seed_event(session, *, external_id, title, category, venue="V"):
    row = Event(
        id=external_id,
        external_id=external_id,
        source="test",
        title=title,
        start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
        venue_name=venue,
        category=category,
        tags=[],
        is_free=False,
        source_url=f"https://example.com/{external_id}",
        raw_data={},
    )
    session.add(row)
    return row


def test_backfill_updates_categories_and_writes_cache(db_session):
    _seed_event(db_session, external_id="a", title="The 27 Club", category="music")
    _seed_event(db_session, external_id="b", title="Concert Real", category="music")
    db_session.commit()

    classifier = _FixedClassifier({
        "The 27 Club": "theater",
        "Concert Real": "music",
    })

    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    b = db_session.query(Event).filter_by(external_id="b").one()
    assert a.category == "theater"
    assert b.category == "music"
    assert db_session.query(EventCategoryCache).count() == 2


def test_backfill_is_idempotent_second_run_uses_cache(db_session):
    _seed_event(db_session, external_id="a", title="The 27 Club", category="music")
    db_session.commit()

    classifier = _FixedClassifier({"The 27 Club": "theater"})

    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()
    assert classifier.calls == 1

    # Second run: no new classifications
    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()
    assert classifier.calls == 1  # still 1


def test_backfill_llm_failure_keeps_provider_category(db_session):
    _seed_event(db_session, external_id="a", title="X", category="music")
    db_session.commit()

    class _Broken:
        def classify(self, event):
            raise RuntimeError("down")

    backfill_categories(db_session, classifier=_Broken(), model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    assert a.category == "music"  # unchanged
    from app.db.models.event_category_cache import EventCategoryCache
    assert db_session.query(EventCategoryCache).count() == 0  # no cache write on error
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/db/test_migration_0006.py -v
```
Expected: FAIL with `ModuleNotFoundError: migration_0006_helpers`.

- [ ] **Step 3: Extract backfill helper**

Create `backend/app/db/migrations/versions/migration_0006_helpers.py`:

```python
"""Backfill helper for migration 0006.

Kept in a normal module (not the versioned migration file) so it can be
imported and tested without invoking Alembic. The migration script itself
is a thin wrapper that calls `backfill_categories`."""
import logging
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.ingestion.categorize import (
    CategoryCache,
    content_hash,
)
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)


class _ClassifierProtocol(Protocol):
    def classify(self, event: NormalizedEvent): ...


def event_row_to_normalized(row: Event) -> NormalizedEvent:
    """Convert a DB row to the NormalizedEvent shape the classifier expects."""
    return NormalizedEvent(
        external_id=row.external_id,
        source=row.source,
        title=row.title,
        description=row.description,
        start_datetime=row.start_datetime,
        end_datetime=row.end_datetime,
        venue_name=row.venue_name,
        venue_address=row.venue_address,
        category=row.category,
        tags=row.tags or [],
        price_min=row.price_min,
        price_max=row.price_max,
        is_free=row.is_free,
        currency=row.currency or "EUR",
        image_url=row.image_url,
        source_url=row.source_url,
        raw_data=row.raw_data or {},
    )


def backfill_categories(
    session: Session,
    classifier: _ClassifierProtocol,
    model_name: str,
) -> None:
    """Iterate every row in `events`, classify, update `category`, and
    populate the cache. Idempotent: existing cache entries short-circuit
    the LLM call. On classifier error, the row is left untouched and no
    cache row is written (so a rerun will retry)."""
    cache = CategoryCache(session, model_name=model_name)
    rows = session.query(Event).all()
    logger.info("backfill_categories: %d events to process", len(rows))

    for i, row in enumerate(rows):
        ev = event_row_to_normalized(row)
        hash_ = content_hash(ev)
        cached = cache.get(hash_)
        if cached is not None:
            if cached != "unknown":
                row.category = cached
            continue

        try:
            decision = classifier.classify(ev)
        except Exception:
            logger.warning("backfill: classifier failed for '%s'", row.title, exc_info=True)
            continue

        if decision.category == "unknown":
            cache.set(hash_, "unknown")
            continue

        cache.set(hash_, decision.category)
        row.category = decision.category

        if (i + 1) % 500 == 0:
            logger.info("backfill_categories: processed %d/%d", i + 1, len(rows))
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/db/test_migration_0006.py -v
```
Expected: all three tests PASS.

- [ ] **Step 5: Create the Alembic migration itself**

Create `backend/app/db/migrations/versions/0006_event_category_cache.py`:

```python
"""Add event_category_cache table and backfill categories via LLM.

Revision ID: 0006_event_category_cache
Revises: 0005_saved_event_kind
Create Date: 2026-07-04 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.config import settings
from app.db.migrations.versions.migration_0006_helpers import backfill_categories
from app.ingestion.categorize import LangchainClassifier


revision: str = "0006_event_category_cache"
down_revision: Union[str, Sequence[str], None] = "0005_saved_event_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_category_cache",
        sa.Column("content_hash", sa.String(), primary_key=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        classifier = LangchainClassifier()
        backfill_categories(session, classifier=classifier, model_name=settings.categorization_model)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    op.drop_table("event_category_cache")
```

- [ ] **Step 6: Verify the migration is discoverable**

```
python -c "from app.db.migrations.versions.migration_0006_helpers import backfill_categories; print('ok')"
python -c "import importlib; m = importlib.import_module('app.db.migrations.versions'); print('ok')"
```

Expected: both print `ok`.

- [ ] **Step 7: Commit**

```
git add backend/app/db/migrations/versions/0006_event_category_cache.py backend/app/db/migrations/versions/migration_0006_helpers.py backend/tests/db/test_migration_0006.py
git commit -m "feat(db): migration 0006 — event_category_cache + LLM backfill"
```

---

## Task 11: CLI `reclassify` command

**Files:**
- Create: `backend/scripts/reclassify.py`
- Test: `backend/tests/scripts/test_reclassify.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/scripts/test_reclassify.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision
from scripts.reclassify import reclassify_all, reclassify_sample

_BERLIN = ZoneInfo("Europe/Berlin")


class _MapClassifier:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def classify(self, event):
        self.calls.append(event.title)
        return CategoryDecision(category=self.mapping.get(event.title, "unknown"))


def _seed(session, title, category):
    session.add(Event(
        id=title, external_id=title, source="test", title=title,
        start_datetime=datetime(2026, 8, 1, tzinfo=_BERLIN),
        venue_name="V", category=category, tags=[], is_free=False,
        source_url=f"https://x/{title}", raw_data={},
    ))


def test_reclassify_all_bypasses_cache(db_session):
    _seed(db_session, "The 27 Club", "music")
    db_session.commit()
    # Prime cache with a stale value
    db_session.add(EventCategoryCache(content_hash="anyhash", category="music", model="m"))
    db_session.commit()

    classifier = _MapClassifier({"The 27 Club": "theater"})
    reclassify_all(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    row = db_session.query(Event).filter_by(title="The 27 Club").one()
    assert row.category == "theater"
    assert "The 27 Club" in classifier.calls


def test_reclassify_sample_does_not_persist(db_session, capsys):
    _seed(db_session, "The 27 Club", "music")
    db_session.commit()

    classifier = _MapClassifier({"The 27 Club": "theater"})
    reclassify_sample(db_session, classifier=classifier, model_name="m", limit=10)

    # DB category unchanged
    row = db_session.query(Event).filter_by(title="The 27 Club").one()
    assert row.category == "music"

    captured = capsys.readouterr()
    assert "The 27 Club" in captured.out
    assert "music" in captured.out  # provider hint
    assert "theater" in captured.out  # LLM decision
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/scripts/test_reclassify.py -v
```
Expected: FAIL with `ModuleNotFoundError: scripts.reclassify`.

- [ ] **Step 3: Implement the script**

Create `backend/scripts/reclassify.py`:

```python
"""Reclassification CLI.

Usage:
  python -m scripts.reclassify --all
  python -m scripts.reclassify --sample 50

`--all` bypasses the cache and re-classifies every event, updating the DB
and rewriting cache rows. Use after prompt or model changes.

`--sample N` picks N random events, classifies them, and prints a table
comparing provider hint vs LLM decision. Does NOT touch the DB. Use to
validate prompt/model tweaks before committing to a full reclassify."""
import argparse
import logging
import random

from sqlalchemy.orm import Session

from app.config import settings
from app.db.migrations.versions.migration_0006_helpers import event_row_to_normalized
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.db.session import SessionLocal
from app.ingestion.categorize import (
    CategoryCache,
    LangchainClassifier,
    content_hash,
)

logger = logging.getLogger(__name__)


def reclassify_all(session: Session, classifier, model_name: str) -> None:
    """Bypass cache: re-classify every event and rewrite cache rows."""
    cache = CategoryCache(session, model_name=model_name)
    rows = session.query(Event).all()
    logger.info("reclassify_all: %d events", len(rows))

    for i, row in enumerate(rows):
        ev = event_row_to_normalized(row)
        try:
            decision = classifier.classify(ev)
        except Exception:
            logger.warning("reclassify: classifier failed for '%s'", row.title, exc_info=True)
            continue

        hash_ = content_hash(ev)
        # Delete stale cache row (if any) then insert fresh
        session.query(EventCategoryCache).filter_by(content_hash=hash_).delete()
        cache.set(hash_, decision.category if decision.category != "unknown" else "unknown")

        if decision.category != "unknown":
            row.category = decision.category

        if (i + 1) % 500 == 0:
            logger.info("reclassify_all: processed %d/%d", i + 1, len(rows))


def reclassify_sample(session: Session, classifier, model_name: str, limit: int) -> None:
    """Classify a random sample WITHOUT touching the DB. Prints a comparison table."""
    all_rows = session.query(Event).all()
    if not all_rows:
        print("(no events in DB)")
        return
    sample = random.sample(all_rows, min(limit, len(all_rows)))

    print(f"{'title':60} | {'provider':>10} | {'llm':>10}")
    print("-" * 90)
    for row in sample:
        ev = event_row_to_normalized(row)
        try:
            decision = classifier.classify(ev)
            llm = decision.category
        except Exception as exc:
            llm = f"ERR({type(exc).__name__})"
        print(f"{row.title[:60]:60} | {row.category:>10} | {llm:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassify events via LLM.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="re-classify every event")
    group.add_argument("--sample", type=int, metavar="N", help="dry-run N random events")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    classifier = LangchainClassifier()
    session = SessionLocal()
    try:
        if args.all:
            reclassify_all(session, classifier=classifier, model_name=settings.categorization_model)
            session.commit()
        else:
            reclassify_sample(session, classifier=classifier, model_name=settings.categorization_model, limit=args.sample)
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/scripts/test_reclassify.py -v
```
Expected: both tests PASS.

- [ ] **Step 5: Smoke-test the CLI arg parser**

```
python -m scripts.reclassify --help
```
Expected: usage message with `--all` and `--sample` options.

- [ ] **Step 6: Commit**

```
git add backend/scripts/reclassify.py backend/tests/scripts/test_reclassify.py
git commit -m "feat(scripts): reclassify --all / --sample CLI"
```

---

## Task 12: Full-suite sanity check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend test suite**

```
pytest -x -q
```
Expected: all tests PASS. If anything unrelated broke, fix it before proceeding.

- [ ] **Step 2: Verify migration head is current**

```
python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; s = ScriptDirectory.from_config(Config('alembic.ini')); print(s.get_current_head())"
```
Expected: prints `0006_event_category_cache`.

- [ ] **Step 3: Confirm imports resolve**

```
python -c "from app.ingestion.categorize import refine_category, CategoryCache, LangchainClassifier, build_categorization_llm, content_hash, CategoryDecision; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 4: If anything above failed, fix and repeat before committing this task's marker**

- [ ] **Step 5: Commit a marker if any lint / mypy adjustments were needed; otherwise skip**

---

## Verification checklist (post-implementation)

- `pytest -x` — all green
- `alembic upgrade head` in a scratch DB — completes without error (skip if no LLM key available; use `--sql` for dry-run)
- Manual `python -m scripts.reclassify --sample 20` against a populated DB — sanity-check the output on real events like "The 27 Club" showing `music → theater`

---

## Files touched summary

Created:
- `backend/app/db/models/event_category_cache.py`
- `backend/app/db/migrations/versions/0006_event_category_cache.py`
- `backend/app/db/migrations/versions/migration_0006_helpers.py`
- `backend/app/ingestion/categorize.py`
- `backend/app/ingestion/categorize_prompts.py`
- `backend/scripts/reclassify.py`
- `backend/tests/ingestion/test_categorize.py`
- `backend/tests/ingestion/test_categorize_prompts.py`
- `backend/tests/db/test_event_category_cache.py`
- `backend/tests/db/test_migration_0006.py`
- `backend/tests/scripts/test_reclassify.py`
- `backend/tests/test_config.py` (if it didn't already exist)

Modified:
- `backend/app/config.py`
- `backend/app/db/models/__init__.py`
- `backend/app/ingestion/scheduler.py`
- `backend/tests/ingestion/test_scheduler.py`
