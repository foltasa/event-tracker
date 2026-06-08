# Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the event ingestion pipeline: Eventbrite + Ticketmaster API adapters, heuteinhamburg.de scraper, SQLite upsert layer, APScheduler daily job, and FastAPI app entry point with a manual trigger endpoint.

**Architecture:** Injected `httpx.Client` pattern — each adapter takes an optional client, defaulting to a real one in production and accepting a fake in tests. `run_ingestion()` is a plain callable (not scheduler-bound) that fetches all sources, upserts to SQLite, and deactivates past events; APScheduler calls it at 04:00 Europe/Berlin. Chroma embedding is stubbed and deferred to the RAG feature.

**Tech Stack:** Python 3.11+, FastAPI, httpx, BeautifulSoup4, APScheduler 3.x, SQLAlchemy 2.0, pytest

---

## File Map

**Create:**
- `backend/app/ingestion/base.py` — SourceAdapter Protocol
- `backend/app/ingestion/eventbrite.py` — Eventbrite API adapter
- `backend/app/ingestion/ticketmaster.py` — Ticketmaster Discovery API adapter
- `backend/app/ingestion/scrapers/__init__.py` — package init (empty)
- `backend/app/ingestion/scrapers/hamburg.py` — heuteinhamburg.de scraper
- `backend/app/ingestion/scheduler.py` — run_ingestion() + create_scheduler() + embed stub
- `backend/app/main.py` — FastAPI app, lifespan, GET /health, POST /ingestion/run
- `backend/tests/ingestion/test_eventbrite.py`
- `backend/tests/ingestion/test_ticketmaster.py`
- `backend/tests/ingestion/test_hamburg_scraper.py`
- `backend/tests/ingestion/test_scheduler.py`
- `backend/tests/api/__init__.py`
- `backend/tests/api/test_main.py`

**Modify:**
- `backend/pyproject.toml` — add fastapi, uvicorn, httpx, beautifulsoup4, apscheduler, pytz, tzdata
- `backend/app/config.py` — add eventbrite_token, ticketmaster_api_key
- `backend/.env.example` — add new key stubs
- `backend/app/ingestion/normalize.py` — add UpsertReport, upsert_events, deactivate_past_events
- `backend/tests/ingestion/test_normalize.py` — add upsert + deactivate tests

---

## Parallelization note

Tasks 1 → 2 → 3 must run in order (dependencies, then protocol, then upsert layer).
Tasks 4, 5, 6 (adapters) are fully independent of each other and can run in parallel after Task 3.
Task 7 (scheduler) needs Tasks 3–6 complete.
Task 8 (main.py) needs Task 7 complete.

---

### Task 1: Dependencies and configuration

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Update pyproject.toml**

Replace the entire `[project]` block's `dependencies` list in `backend/pyproject.toml` with:

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
]
```

Also update the `dev` optional-dependencies to include httpx (needed for test client):

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 2: Install updated dependencies**

Run from `backend/`:
```
pip install -e ".[dev]"
```

Expected: installs without error. Verify with `python -c "import httpx, bs4, apscheduler, fastapi; print('ok')"`.

- [ ] **Step 3: Replace backend/app/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
```

- [ ] **Step 4: Append to backend/.env.example**

Add these two lines at the end:
```
EVENTBRITE_TOKEN=your_eventbrite_token_here
TICKETMASTER_API_KEY=your_ticketmaster_api_key_here
```

- [ ] **Step 5: Verify existing tests still pass**

```
cd backend && pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/.env.example
git commit -m "chore: add ingestion pipeline dependencies and config keys"
```

---

### Task 2: SourceAdapter Protocol

**Files:**
- Create: `backend/app/ingestion/base.py`

- [ ] **Step 1: Create base.py**

```python
from typing import Iterator, Protocol

from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(self) -> Iterator[NormalizedEvent]: ...
```

- [ ] **Step 2: Verify import resolves**

```
cd backend && python -c "from app.ingestion.base import SourceAdapter; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/ingestion/base.py
git commit -m "feat: add SourceAdapter protocol"
```

---

### Task 3: Upsert layer (TDD)

**Files:**
- Modify: `backend/app/ingestion/normalize.py`
- Modify: `backend/tests/ingestion/test_normalize.py`

- [ ] **Step 1: Append failing tests to test_normalize.py**

Add the following at the bottom of `backend/tests/ingestion/test_normalize.py` (keep all existing content):

```python
# ---------------------------------------------------------------------------
# Upsert + deactivation tests (added in ingestion pipeline task)
# ---------------------------------------------------------------------------
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events  # noqa: E402
from datetime import timedelta


def _normed_event(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="src_001",
        source="eventbrite",
        title="Test Event",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=BERLIN),
        category="music",
        is_free=False,
        price_min=10.0,
        price_max=20.0,
        source_url="https://example.com/e/001",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_upsert_inserts_new_event(db_session):
    report = upsert_events(db_session, [_normed_event()])
    db_session.commit()
    assert report.inserted == 1
    assert report.updated == 0
    assert report.skipped == 0


def test_upsert_updates_existing_event(db_session):
    upsert_events(db_session, [_normed_event(title="Original")])
    db_session.commit()

    report = upsert_events(db_session, [_normed_event(title="Updated")])
    db_session.commit()

    assert report.inserted == 0
    assert report.updated == 1

    from app.db.models.event import Event
    ev = db_session.query(Event).filter_by(external_id="src_001", source="eventbrite").one()
    assert ev.title == "Updated"


def test_upsert_is_idempotent(db_session):
    events = [_normed_event()]
    upsert_events(db_session, events)
    db_session.commit()
    report = upsert_events(db_session, events)
    db_session.commit()

    from app.db.models.event import Event
    assert db_session.query(Event).count() == 1
    assert report.updated == 1


def test_upsert_handles_multiple_sources(db_session):
    report = upsert_events(db_session, [
        _normed_event(source="eventbrite", external_id="001"),
        _normed_event(source="ticketmaster", external_id="001"),
    ])
    db_session.commit()
    assert report.inserted == 2


def test_deactivate_past_events(db_session):
    now = datetime.now(tz=timezone.utc)
    past = _normed_event(external_id="past", start_datetime=now - timedelta(days=1))
    future = _normed_event(external_id="future", start_datetime=now + timedelta(days=1))

    upsert_events(db_session, [past, future])
    db_session.commit()

    count = deactivate_past_events(db_session)
    db_session.commit()

    from app.db.models.event import Event
    past_ev = db_session.query(Event).filter_by(external_id="past").one()
    future_ev = db_session.query(Event).filter_by(external_id="future").one()

    assert count == 1
    assert past_ev.is_active is False
    assert future_ev.is_active is True


def test_deactivate_does_not_double_count_already_inactive(db_session):
    now = datetime.now(tz=timezone.utc)
    past = _normed_event(external_id="past", start_datetime=now - timedelta(days=1))
    upsert_events(db_session, [past])
    db_session.commit()

    deactivate_past_events(db_session)
    db_session.commit()
    count = deactivate_past_events(db_session)
    db_session.commit()

    assert count == 0
```

Note: the top of `test_normalize.py` already imports `datetime`, `timezone`, `BERLIN`, `NormalizedEvent`, and `pytest` — the new tests reuse those.

- [ ] **Step 2: Run to verify failure**

```
cd backend && pytest tests/ingestion/test_normalize.py -k "upsert or deactivate" -v
```

Expected: `ImportError` — `upsert_events` not yet defined.

- [ ] **Step 3: Append implementation to normalize.py**

Add to the bottom of `backend/app/ingestion/normalize.py`:

```python
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models.event import Event

logger = logging.getLogger(__name__)

_MUTABLE_FIELDS = (
    "title", "description", "summary", "start_datetime", "end_datetime",
    "venue_name", "venue_address", "latitude", "longitude",
    "category", "tags", "price_min", "price_max", "is_free",
    "currency", "image_url", "source_url", "raw_data",
)


@dataclass
class UpsertReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def upsert_events(session: Session, events: Iterable[NormalizedEvent]) -> UpsertReport:
    """Insert or update events keyed by (external_id, source). Does not commit."""
    report = UpsertReport()
    for ev in events:
        try:
            existing = (
                session.query(Event)
                .filter_by(external_id=ev.external_id, source=ev.source)
                .one_or_none()
            )
            if existing:
                for f in _MUTABLE_FIELDS:
                    setattr(existing, f, getattr(ev, f))
                existing.updated_at = datetime.now(timezone.utc)
                report.updated += 1
            else:
                row = Event(id=str(uuid.uuid4()), **ev.model_dump())
                session.add(row)
                report.inserted += 1
        except Exception:
            logger.exception("Failed to upsert event %s/%s", ev.source, ev.external_id)
            report.skipped += 1
    return report


def deactivate_past_events(session: Session) -> int:
    """Set is_active=False for events whose start_datetime is in the past. Does not commit."""
    now = datetime.now(timezone.utc)
    return (
        session.query(Event)
        .filter(Event.start_datetime < now, Event.is_active.is_(True))
        .update({"is_active": False}, synchronize_session="fetch")
    )
```

- [ ] **Step 4: Run new tests**

```
cd backend && pytest tests/ingestion/test_normalize.py -k "upsert or deactivate" -v
```

Expected: all 6 new tests PASS.

- [ ] **Step 5: Run full test suite**

```
cd backend && pytest tests/ -v
```

Expected: all tests pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/normalize.py backend/tests/ingestion/test_normalize.py
git commit -m "feat: add upsert_events and deactivate_past_events"
```

---

### Task 4: Eventbrite adapter (TDD)

**Files:**
- Create: `backend/app/ingestion/eventbrite.py`
- Create: `backend/tests/ingestion/test_eventbrite.py`

**Can run in parallel with Tasks 5 and 6.**

- [ ] **Step 1: Create test file**

Create `backend/tests/ingestion/test_eventbrite.py`:

```python
import httpx
import pytest

from app.ingestion.eventbrite import EventbriteAdapter

_EVENT_1 = {
    "id": "eb_001",
    "name": {"text": "Jazz Night at Mojo Club"},
    "description": {"text": "A jazz evening with local musicians."},
    "summary": "Intimate trio set",
    "url": "https://www.eventbrite.de/e/jazz-night-001",
    "start": {"utc": "2026-06-14T18:00:00Z"},
    "end": {"utc": "2026-06-14T21:00:00Z"},
    "is_free": False,
    "logo": {"url": "https://img.evbuc.com/img.jpg"},
    "category": {"name": "Music"},
    "venue": {
        "name": "Mojo Club",
        "address": {"localized_address_display": "Reeperbahn 1, 20359 Hamburg"},
        "latitude": "53.5497",
        "longitude": "9.9657",
    },
    "ticket_availability": {
        "minimum_ticket_price": {"major_value": "18.00"},
        "maximum_ticket_price": {"major_value": "24.00"},
    },
    "tags": [],
}

_EVENT_FREE = {
    **_EVENT_1,
    "id": "eb_002",
    "url": "https://www.eventbrite.de/e/free-event-002",
    "is_free": True,
    "ticket_availability": None,
    "category": {"name": "Arts"},
}

_PAGE_1 = {
    "events": [_EVENT_1],
    "pagination": {"has_more_items": True, "continuation": "page2token"},
}
_PAGE_2 = {
    "events": [_EVENT_FREE],
    "pagination": {"has_more_items": False, "continuation": None},
}
_EMPTY = {"events": [], "pagination": {"has_more_items": False, "continuation": None}}


class _FakeClient:
    def __init__(self, pages: list[dict]):
        self._pages = iter(pages)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return httpx.Response(200, json=next(self._pages),
                              request=httpx.Request("GET", url))


def test_fetch_maps_music_event():
    adapter = EventbriteAdapter(client=_FakeClient([_PAGE_1, _EMPTY]))
    events = list(adapter.fetch())
    assert len(events) == 1
    e = events[0]
    assert e.external_id == "eb_001"
    assert e.source == "eventbrite"
    assert e.title == "Jazz Night at Mojo Club"
    assert e.category == "music"
    assert e.is_free is False
    assert e.price_min == 18.0
    assert e.price_max == 24.0
    assert e.venue_name == "Mojo Club"
    assert e.venue_address == "Reeperbahn 1, 20359 Hamburg"
    assert abs(e.latitude - 53.5497) < 0.001
    assert e.start_datetime.tzinfo is not None


def test_fetch_paginates():
    adapter = EventbriteAdapter(client=_FakeClient([_PAGE_1, _PAGE_2]))
    events = list(adapter.fetch())
    assert len(events) == 2
    assert events[1].external_id == "eb_002"


def test_fetch_maps_free_event():
    page = {"events": [_EVENT_FREE], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert events[0].is_free is True
    assert events[0].price_min is None
    assert events[0].price_max is None


def test_fetch_maps_arts_category():
    page = {"events": [_EVENT_FREE], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert events[0].category == "arts"


def test_fetch_returns_empty_on_no_events():
    adapter = EventbriteAdapter(client=_FakeClient([_EMPTY]))
    assert list(adapter.fetch()) == []


def test_fetch_skips_malformed_event():
    bad = {"id": "eb_bad"}  # missing name, url, start
    page = {"events": [bad, _EVENT_1], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].external_id == "eb_001"
```

- [ ] **Step 2: Run to verify failure**

```
cd backend && pytest tests/ingestion/test_eventbrite.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.eventbrite'`

- [ ] **Step 3: Create eventbrite.py**

Create `backend/app/ingestion/eventbrite.py`:

```python
import logging
from datetime import datetime
from typing import Iterator

import httpx

from app.config import settings
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.eventbriteapi.com/v3"

_CATEGORY_MAP: dict[str, str] = {
    "music": "music",
    "arts": "arts",
    "visual arts": "arts",
    "performing arts": "theater",
    "performing & visual arts": "theater",
    "film & media": "film",
    "food & drink": "food",
    "sports & fitness": "sports",
    "science & tech": "tech",
    "outdoors & adventure": "outdoor",
    "family & education": "family",
    "theater": "theater",
}


def _map_category(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.lower().strip(), "other")


def _parse_prices(
    ticket_availability: dict | None, is_free: bool
) -> tuple[float | None, float | None]:
    if is_free or not ticket_availability:
        return None, None
    lo = ticket_availability.get("minimum_ticket_price")
    hi = ticket_availability.get("maximum_ticket_price")
    return (
        float(lo["major_value"]) if lo else None,
        float(hi["major_value"]) if hi else None,
    )


class EventbriteAdapter:
    name = "eventbrite"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._token = settings.eventbrite_token

    def fetch(self) -> Iterator[NormalizedEvent]:
        params: dict = {
            "location.address": "Hamburg, Germany",
            "location.within": "20km",
            "expand": "venue,category,ticket_availability",
            "page_size": 50,
        }
        if self._token:
            params["token"] = self._token

        continuation: str | None = None
        while True:
            if continuation:
                params["continuation"] = continuation

            resp = self._client.get(f"{_BASE_URL}/events/search/", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("events", []):
                event = self._parse(raw)
                if event:
                    yield event

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break
            continuation = pagination.get("continuation")
            if not continuation:
                break

    def _parse(self, raw: dict) -> NormalizedEvent | None:
        try:
            venue = raw.get("venue") or {}
            address = venue.get("address") or {}
            category_obj = raw.get("category") or {}
            is_free = raw.get("is_free", False)
            price_min, price_max = _parse_prices(raw.get("ticket_availability"), is_free)
            logo = raw.get("logo") or {}
            end_raw = (raw.get("end") or {}).get("utc")

            return NormalizedEvent(
                external_id=str(raw["id"]),
                source=self.name,
                title=raw["name"]["text"],
                description=(raw.get("description") or {}).get("text"),
                summary=raw.get("summary"),
                start_datetime=datetime.fromisoformat(
                    raw["start"]["utc"].replace("Z", "+00:00")
                ),
                end_datetime=datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                if end_raw
                else None,
                venue_name=venue.get("name"),
                venue_address=address.get("localized_address_display"),
                latitude=float(venue["latitude"]) if venue.get("latitude") else None,
                longitude=float(venue["longitude"]) if venue.get("longitude") else None,
                category=_map_category(category_obj.get("name", "")),
                tags=[
                    t["display_name"]
                    for t in (raw.get("tags") or [])
                    if t.get("display_name")
                ],
                price_min=price_min,
                price_max=price_max,
                is_free=is_free,
                currency="EUR",
                image_url=logo.get("url"),
                source_url=raw["url"],
                raw_data=raw,
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Skipping malformed Eventbrite event: %s", raw.get("id"))
            return None
```

- [ ] **Step 4: Run tests**

```
cd backend && pytest tests/ingestion/test_eventbrite.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/eventbrite.py backend/tests/ingestion/test_eventbrite.py
git commit -m "feat: add Eventbrite source adapter"
```

---

### Task 5: Ticketmaster adapter (TDD)

**Files:**
- Create: `backend/app/ingestion/ticketmaster.py`
- Create: `backend/tests/ingestion/test_ticketmaster.py`

**Can run in parallel with Tasks 4 and 6.**

- [ ] **Step 1: Create test file**

Create `backend/tests/ingestion/test_ticketmaster.py`:

```python
import httpx
import pytest

from app.ingestion.ticketmaster import TicketmasterAdapter

_EVENT_1 = {
    "id": "tm_001",
    "name": "Rock Concert at Barclays",
    "url": "https://www.ticketmaster.de/event/tm_001",
    "dates": {"start": {"dateTime": "2026-06-20T19:00:00Z"}},
    "images": [
        {"url": "https://s1.ticketm.net/small.jpg", "width": 205, "height": 115},
        {"url": "https://s1.ticketm.net/large.jpg", "width": 640, "height": 360},
    ],
    "priceRanges": [{"min": 25.0, "max": 45.0, "currency": "EUR", "type": "standard"}],
    "_embedded": {
        "venues": [{
            "name": "Barclays Arena",
            "address": {"line1": "Sylvesterallee 10"},
            "city": {"name": "Hamburg"},
            "location": {"latitude": "53.5897", "longitude": "9.9016"},
        }]
    },
    "classifications": [{
        "segment": {"name": "Music"},
        "genre": {"name": "Rock"},
        "primary": True,
    }],
}

_EVENT_SPORTS = {
    **_EVENT_1,
    "id": "tm_002",
    "url": "https://www.ticketmaster.de/event/tm_002",
    "classifications": [{"segment": {"name": "Sports"}, "genre": {"name": "Football"}, "primary": True}],
    "priceRanges": [],
}

_PAGE_1 = {
    "_embedded": {"events": [_EVENT_1]},
    "page": {"totalPages": 2, "number": 0, "size": 200, "totalElements": 2},
}
_PAGE_2 = {
    "_embedded": {"events": [_EVENT_SPORTS]},
    "page": {"totalPages": 2, "number": 1, "size": 200, "totalElements": 2},
}
_EMPTY = {"page": {"totalPages": 0, "number": 0, "size": 200, "totalElements": 0}}


class _FakeClient:
    def __init__(self, pages: list[dict]):
        self._pages = iter(pages)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return httpx.Response(200, json=next(self._pages),
                              request=httpx.Request("GET", url))


def test_fetch_maps_music_event():
    adapter = TicketmasterAdapter(client=_FakeClient([_PAGE_1, _EMPTY]))
    events = list(adapter.fetch())
    assert len(events) == 1
    e = events[0]
    assert e.external_id == "tm_001"
    assert e.source == "ticketmaster"
    assert e.title == "Rock Concert at Barclays"
    assert e.category == "music"
    assert e.price_min == 25.0
    assert e.price_max == 45.0
    assert e.venue_name == "Barclays Arena"
    assert abs(e.latitude - 53.5897) < 0.001
    assert e.start_datetime.tzinfo is not None


def test_fetch_picks_largest_image():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_1]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].image_url == "https://s1.ticketm.net/large.jpg"


def test_fetch_paginates():
    adapter = TicketmasterAdapter(client=_FakeClient([_PAGE_1, _PAGE_2]))
    events = list(adapter.fetch())
    assert len(events) == 2


def test_fetch_maps_sports_category():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_SPORTS]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].category == "sports"


def test_fetch_no_price_range_yields_none():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_SPORTS]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].price_min is None
    assert events[0].price_max is None
    assert events[0].is_free is False


def test_fetch_returns_empty_when_no_embedded():
    adapter = TicketmasterAdapter(client=_FakeClient([_EMPTY]))
    assert list(adapter.fetch()) == []


def test_fetch_skips_malformed_event():
    bad = {"id": "tm_bad"}
    page = {"_embedded": {"events": [bad, _EVENT_1]}, "page": {"totalPages": 1, "number": 0}}
    adapter = TicketmasterAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].external_id == "tm_001"
```

- [ ] **Step 2: Run to verify failure**

```
cd backend && pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.ticketmaster'`

- [ ] **Step 3: Create ticketmaster.py**

Create `backend/app/ingestion/ticketmaster.py`:

```python
import logging
from datetime import datetime
from typing import Iterator

import httpx

from app.config import settings
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.ticketmaster.com/discovery/v2"

_SEGMENT_MAP: dict[str, str] = {
    "music": "music",
    "arts & theatre": "theater",
    "arts & theater": "theater",
    "sports": "sports",
    "film": "film",
    "family": "family",
    "miscellaneous": "other",
}

_GENRE_OVERRIDE: dict[str, str] = {
    "classical": "arts",
    "opera": "theater",
    "ballet": "arts",
    "comedy": "theater",
}


def _map_category(classifications: list[dict]) -> str:
    for cls in classifications:
        if not cls.get("primary"):
            continue
        genre = cls.get("genre", {}).get("name", "").lower()
        if genre in _GENRE_OVERRIDE:
            return _GENRE_OVERRIDE[genre]
        segment = cls.get("segment", {}).get("name", "").lower()
        return _SEGMENT_MAP.get(segment, "other")
    return "other"


def _best_image(images: list[dict]) -> str | None:
    if not images:
        return None
    return max(images, key=lambda i: i.get("width", 0) * i.get("height", 0)).get("url")


class TicketmasterAdapter:
    name = "ticketmaster"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key

    def fetch(self) -> Iterator[NormalizedEvent]:
        params: dict = {
            "city": "Hamburg",
            "countryCode": "DE",
            "size": 200,
            "page": 0,
        }
        if self._api_key:
            params["apikey"] = self._api_key

        while True:
            resp = self._client.get(f"{_BASE_URL}/events.json", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("_embedded", {}).get("events", []):
                event = self._parse(raw)
                if event:
                    yield event

            page_info = data.get("page", {})
            total = page_info.get("totalPages", 1)
            current = page_info.get("number", 0)
            if current + 1 >= total:
                break
            params["page"] = current + 1

    def _parse(self, raw: dict) -> NormalizedEvent | None:
        try:
            start_str = raw["dates"]["start"]["dateTime"]
            venues = raw.get("_embedded", {}).get("venues", [{}])
            venue = venues[0] if venues else {}
            loc = venue.get("location", {})
            line1 = venue.get("address", {}).get("line1", "")
            city = venue.get("city", {}).get("name", "Hamburg")
            venue_address = f"{line1}, {city}".strip(", ") or None

            ranges = raw.get("priceRanges") or []
            price_min = min((p["min"] for p in ranges if "min" in p), default=None)
            price_max = max((p["max"] for p in ranges if "max" in p), default=None)

            return NormalizedEvent(
                external_id=str(raw["id"]),
                source=self.name,
                title=raw["name"],
                start_datetime=datetime.fromisoformat(start_str.replace("Z", "+00:00")),
                venue_name=venue.get("name"),
                venue_address=venue_address,
                latitude=float(loc["latitude"]) if loc.get("latitude") else None,
                longitude=float(loc["longitude"]) if loc.get("longitude") else None,
                category=_map_category(raw.get("classifications") or []),
                tags=[],
                price_min=price_min,
                price_max=price_max,
                is_free=False,
                currency="EUR",
                image_url=_best_image(raw.get("images") or []),
                source_url=raw["url"],
                raw_data=raw,
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Skipping malformed Ticketmaster event: %s", raw.get("id"))
            return None
```

- [ ] **Step 4: Run tests**

```
cd backend && pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/ticketmaster.py backend/tests/ingestion/test_ticketmaster.py
git commit -m "feat: add Ticketmaster source adapter"
```

---

### Task 6: Hamburg scraper (TDD)

**Files:**
- Create: `backend/app/ingestion/scrapers/__init__.py`
- Create: `backend/app/ingestion/scrapers/hamburg.py`
- Create: `backend/tests/ingestion/test_hamburg_scraper.py`

**Can run in parallel with Tasks 4 and 5.**

- [ ] **Step 1: Create scrapers package**

Create `backend/app/ingestion/scrapers/__init__.py` — empty file.

- [ ] **Step 2: Create test file**

Create `backend/tests/ingestion/test_hamburg_scraper.py`:

```python
import httpx
import pytest

from app.ingestion.scrapers.hamburg import HamburgScraper

_HTML = """<!DOCTYPE html>
<html><body><main>
  <a href="/event/jazz-night-mojo"><img src="https://cdn.heuteinhamburg.de/img1.jpg" alt="Jazz Night"></a>
  <a href="/kategorie/musik">Musik</a>
  <a href="/event/jazz-night-mojo">Jazz Night at Mojo Club</a>
  <img src="/icons/icon-clock.svg" alt="Icon"> 20:30 Uhr
  <a href="https://maps.google.com/?q=Mojo+Club">
    <img src="/icons/icon-map.svg" alt="Icon"> Mojo Club
  </a>
  <a href="https://tickets.example.com/jazz">
    <img src="/icons/icon-ticket.svg" alt="Icon"> 18 €
  </a>

  <a href="/event/free-concert"><img src="https://cdn.heuteinhamburg.de/img2.jpg" alt="Free Concert"></a>
  <a href="/kategorie/outdoor">Outdoor</a>
  <a href="/event/free-concert">Free Summer Concert</a>
  <img src="/icons/icon-clock.svg" alt="Icon"> 16:00 Uhr
  <a href="https://maps.google.com/?q=Stadtpark">
    <img src="/icons/icon-map.svg" alt="Icon"> Stadtpark
  </a>
  <a href="#">
    <img src="/icons/icon-ticket.svg" alt="Icon"> kostenlos
  </a>
</main></body></html>"""

_EMPTY_HTML = "<html><body><main></main></body></html>"


class _FakeClient:
    def __init__(self, html: str, status_code: int = 200):
        self._html = html
        self._status_code = status_code

    def get(self, url: str, **kwargs) -> httpx.Response:
        return httpx.Response(
            self._status_code,
            text=self._html,
            request=httpx.Request("GET", url),
        )


def test_returns_two_events():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert len(events) == 2


def test_title_and_url():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].title == "Jazz Night at Mojo Club"
    assert events[0].source_url == "https://heuteinhamburg.de/event/jazz-night-mojo"
    assert events[0].external_id == "jazz-night-mojo"
    assert events[0].source == "hamburg_scraper"


def test_venue():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].venue_name == "Mojo Club"


def test_paid_price():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].is_free is False
    assert events[0].price_min == 18.0


def test_free_event():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[1].is_free is True
    assert events[1].price_min is None


def test_category_music():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].category == "music"


def test_category_outdoor():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[1].category == "outdoor"


def test_image_url():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].image_url == "https://cdn.heuteinhamburg.de/img1.jpg"


def test_empty_page():
    assert list(HamburgScraper(client=_FakeClient(_EMPTY_HTML)).fetch()) == []


def test_http_error_raises():
    with pytest.raises(Exception):
        list(HamburgScraper(client=_FakeClient("", status_code=500)).fetch())
```

- [ ] **Step 3: Run to verify failure**

```
cd backend && pytest tests/ingestion/test_hamburg_scraper.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.scrapers.hamburg'`

- [ ] **Step 4: Create hamburg.py**

Create `backend/app/ingestion/scrapers/hamburg.py`:

```python
import logging
import re
from datetime import date, datetime, time
from typing import Iterator
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://heuteinhamburg.de"
_BERLIN = ZoneInfo("Europe/Berlin")

_CATEGORY_MAP: dict[str, str] = {
    "musik": "music",
    "konzert": "music",
    "kunst": "arts",
    "ausstellung": "arts",
    "kultur": "arts",
    "kino": "film",
    "film": "film",
    "theater": "theater",
    "show": "theater",
    "comedy": "theater",
    "sport": "sports",
    "outdoor": "outdoor",
    "natur": "outdoor",
    "food": "food",
    "essen": "food",
    "genuss": "food",
    "tech": "tech",
    "technologie": "tech",
    "kinder": "family",
    "familie": "family",
}


def _map_category(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.lower().strip(), "other")


def _parse_price(text: str) -> tuple[bool, float | None, float | None]:
    """Returns (is_free, price_min, price_max)."""
    cleaned = text.strip().lower()
    if any(w in cleaned for w in ("kostenlos", "gratis", "frei", "free")):
        return True, None, None
    nums = re.findall(r"\d+(?:[.,]\d+)?", cleaned)
    if not nums:
        return False, None, None
    prices = [float(n.replace(",", ".")) for n in nums]
    return False, prices[0], prices[-1] if len(prices) > 1 else None


def _parse_time(text: str, today: date) -> datetime | None:
    """Parse '20:30 Uhr' or 'ab 20:00 Uhr' into a tz-aware datetime."""
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    return datetime.combine(today, time(int(m.group(1)), int(m.group(2))), tzinfo=_BERLIN)


class HamburgScraper:
    name = "hamburg_scraper"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": "EventTrackerBot/1.0"}
        )

    def fetch(self) -> Iterator[NormalizedEvent]:
        resp = self._client.get(_BASE_URL)
        resp.raise_for_status()

        today = datetime.now(tz=_BERLIN).date()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if not href.startswith("/event/"):
                continue
            if link.find("img"):
                continue  # skip image-only anchors
            title = link.get_text(strip=True)
            if not title:
                continue
            slug = href.split("/event/", 1)[1].split("/")[0]
            if not slug or slug in seen:
                continue
            seen.add(slug)

            ev = self._parse_card(soup, link, slug, title, today)
            if ev:
                yield ev

    def _parse_card(self, soup, title_link, slug: str, title: str, today: date) -> NormalizedEvent | None:
        try:
            source_url = f"{_BASE_URL}/event/{slug}"

            # Category from nearest preceding /kategorie/ link
            cat_link = title_link.find_previous("a", href=lambda h: h and "/kategorie/" in h)
            cat_text = cat_link.get_text(strip=True) if cat_link else ""
            category = _map_category(cat_text)
            tags = [cat_text.lower()] if cat_text else []

            # Image: preceding anchor to same event href that wraps an img
            image_url: str | None = None
            img_anchor = title_link.find_previous("a", href=f"/event/{slug}")
            if img_anchor:
                img_tag = img_anchor.find("img")
                if img_tag:
                    src = img_tag.get("src", "")
                    if src and "icon" not in src:
                        image_url = src if src.startswith("http") else _BASE_URL + src

            # Time from nearest following clock icon
            clock = title_link.find_next("img", attrs={"src": "/icons/icon-clock.svg"})
            start_datetime: datetime
            if clock and clock.next_sibling:
                parsed = _parse_time(str(clock.next_sibling), today)
                start_datetime = parsed or datetime.combine(today, time(0, 0), tzinfo=_BERLIN)
            else:
                start_datetime = datetime.combine(today, time(0, 0), tzinfo=_BERLIN)

            # Venue from nearest following map icon's parent anchor
            venue_name: str | None = None
            map_img = title_link.find_next("img", attrs={"src": "/icons/icon-map.svg"})
            if map_img:
                venue_name = map_img.parent.get_text(strip=True) or None

            # Price from nearest following ticket icon's parent anchor
            is_free, price_min, price_max = False, None, None
            ticket_img = title_link.find_next("img", attrs={"src": "/icons/icon-ticket.svg"})
            if ticket_img:
                is_free, price_min, price_max = _parse_price(
                    ticket_img.parent.get_text(strip=True)
                )

            return NormalizedEvent(
                external_id=slug,
                source=self.name,
                title=title,
                start_datetime=start_datetime,
                venue_name=venue_name,
                category=category,
                tags=tags,
                is_free=is_free,
                price_min=price_min,
                price_max=price_max,
                currency="EUR",
                image_url=image_url,
                source_url=source_url,
                raw_data={"slug": slug},
            )
        except Exception:
            logger.exception("Skipping malformed heuteinhamburg event: %s", slug)
            return None
```

- [ ] **Step 5: Run tests**

```
cd backend && pytest tests/ingestion/test_hamburg_scraper.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/scrapers/ backend/tests/ingestion/test_hamburg_scraper.py
git commit -m "feat: add heuteinhamburg.de scraper adapter"
```

---

### Task 7: Scheduler (TDD)

**Files:**
- Create: `backend/app/ingestion/scheduler.py`
- Create: `backend/tests/ingestion/test_scheduler.py`

**Depends on:** Tasks 3, 4, 5, 6 all complete.

- [ ] **Step 1: Create test file**

Create `backend/tests/ingestion/test_scheduler.py`:

```python
from datetime import datetime, timedelta, timezone
from typing import Iterator
from unittest.mock import patch

import pytest

from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion

_BERLIN = timezone(timedelta(hours=2))


def _ev(slug: str = "evt_1") -> NormalizedEvent:
    return NormalizedEvent(
        external_id=slug,
        source="test",
        title="Test Event",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=_BERLIN),
        category="music",
        is_free=False,
        source_url=f"https://example.com/{slug}",
    )


class _OkAdapter:
    name = "ok"
    def fetch(self) -> Iterator[NormalizedEvent]:
        yield _ev("ok_1")


class _FailAdapter:
    name = "fail"
    def fetch(self) -> Iterator[NormalizedEvent]:
        raise RuntimeError("source down")


def test_inserts_events(db_session):
    report = run_ingestion(adapters=[_OkAdapter()], session=db_session)
    assert report.inserted == 1


def test_failing_adapter_does_not_abort_run(db_session):
    report = run_ingestion(adapters=[_FailAdapter(), _OkAdapter()], session=db_session)
    assert report.inserted == 1


def test_aggregates_across_adapters(db_session):
    class _OkAdapter2:
        name = "ok2"
        def fetch(self):
            yield _ev("ok_2")

    report = run_ingestion(adapters=[_OkAdapter(), _OkAdapter2()], session=db_session)
    assert report.inserted == 2


def test_calls_deactivate(db_session):
    with patch("app.ingestion.scheduler.deactivate_past_events") as mock_deact:
        mock_deact.return_value = 0
        run_ingestion(adapters=[_OkAdapter()], session=db_session)
    mock_deact.assert_called_once_with(db_session)


def test_calls_embed_stub(db_session):
    with patch("app.ingestion.scheduler.embed_new_events") as mock_embed:
        run_ingestion(adapters=[_OkAdapter()], session=db_session)
    mock_embed.assert_called_once_with(db_session)
```

- [ ] **Step 2: Run to verify failure**

```
cd backend && pytest tests/ingestion/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.scheduler'`

- [ ] **Step 3: Create scheduler.py**

Create `backend/app/ingestion/scheduler.py`:

```python
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.ingestion.base import SourceAdapter
from app.ingestion.eventbrite import EventbriteAdapter
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events
from app.ingestion.scrapers.hamburg import HamburgScraper
from app.ingestion.ticketmaster import TicketmasterAdapter

logger = logging.getLogger(__name__)


def embed_new_events(session: Session) -> None:
    """Stub — Chroma embedding deferred to the RAG feature."""
    logger.info("embed_new_events: deferred, skipping")


def _default_adapters() -> list[SourceAdapter]:
    return [EventbriteAdapter(), TicketmasterAdapter(), HamburgScraper()]


def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
) -> UpsertReport:
    """Fetch all sources, upsert to DB, deactivate past events."""
    if adapters is None:
        adapters = _default_adapters()

    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        all_events = []
        for adapter in adapters:
            try:
                batch = list(adapter.fetch())
                all_events.extend(batch)
                logger.info("%s: fetched %d events", adapter.name, len(batch))
            except Exception:
                logger.exception("%s: fetch failed, skipping", adapter.name)

        report = upsert_events(session, all_events)
        deactivate_past_events(session)
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
        raise
    finally:
        if own_session:
            session.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    scheduler.add_job(run_ingestion, "cron", hour=4, minute=0)
    return scheduler
```

- [ ] **Step 4: Run tests**

```
cd backend && pytest tests/ingestion/test_scheduler.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full suite**

```
cd backend && pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat: add ingestion scheduler and run_ingestion orchestrator"
```

---

### Task 8: FastAPI app (TDD)

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/test_main.py`

**Depends on:** Task 7 complete.

- [ ] **Step 1: Create test files**

Create `backend/tests/api/__init__.py` — empty file.

Create `backend/tests/api/test_main.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingestion_run_returns_report(client):
    mock_report = MagicMock(inserted=3, updated=1, skipped=0)
    with patch("app.main.run_ingestion", return_value=mock_report):
        resp = client.post("/ingestion/run")
    assert resp.status_code == 200
    assert resp.json() == {"inserted": 3, "updated": 1, "skipped": 0}


def test_ingestion_run_returns_500_on_failure(client):
    with patch("app.main.run_ingestion", side_effect=RuntimeError("db down")):
        resp = client.post("/ingestion/run")
    assert resp.status_code == 500
```

- [ ] **Step 2: Run to verify failure**

```
cd backend && pytest tests/api/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Create main.py**

Create `backend/app/main.py`:

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingestion/run")
def trigger_ingestion() -> dict:
    try:
        report = run_ingestion()
        return {"inserted": report.inserted, "updated": report.updated, "skipped": report.skipped}
    except Exception as exc:
        logger.exception("Manual ingestion run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests**

```
cd backend && pytest tests/api/test_main.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run full suite**

```
cd backend && pytest tests/ -v
```

Expected: all tests pass with no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/api/
git commit -m "feat: add FastAPI app with scheduler lifespan and POST /ingestion/run"
```
