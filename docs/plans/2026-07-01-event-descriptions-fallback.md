# Event Descriptions Fallback — TM Page Scrape + Hide-Empty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise Ticketmaster description coverage from 5.6% by scraping the public ticketmaster.de event page as a fallback source, backfill existing rows, and hide any events that still lack a description from every user-facing query.

**Architecture:** New shared module `app.ingestion.ticketmaster_page` provides one HTML-extraction function used by both (a) an inline fallback added to `TicketmasterAdapter._parse`, and (b) a one-off backfill script. A new `visible_events_filter()` helper in `app.db.models.event` is applied at every user-facing `Event` query site and to the Chroma embedding feed, so events without descriptions are hidden from the UI, agent, and vector store.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup 4, SQLAlchemy 2.x, pytest — no new dependencies.

**Spec:** `docs/specs/2026-07-01-event-descriptions-fallback-design.md`.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `backend/app/ingestion/ticketmaster_page.py` | Pure HTML → description text extraction |
| Modify | `backend/app/ingestion/ticketmaster.py` | Add page-scrape fallback into `_parse` chain |
| Create | `backend/scripts/backfill_tm_descriptions.py` | One-off backfill for existing DB rows |
| Modify | `backend/app/db/models/event.py` | Add `visible_events_filter()` helper |
| Modify | `backend/app/api/routes_events.py` | Apply filter to list endpoint (leave detail route alone) |
| Modify | `backend/app/api/routes_calendar.py` | (No changes to save/unsave — see spec Part C exclusions) — no query change needed here |
| Modify | `backend/app/agent/tools.py` | Apply filter to `search_events`, `get_recommendations` |
| Modify | `backend/app/ingestion/scheduler.py` | Apply filter to `embed_new_events`; extend stale-vector sweep |
| Create | `backend/tests/fixtures/__init__.py` | Empty package marker |
| Create | `backend/tests/fixtures/ticketmaster_page_sample.html` | Real ticketmaster.de page HTML (from recon) |
| Create | `backend/tests/ingestion/test_ticketmaster_page.py` | Unit tests for `extract_description` |
| Modify | `backend/tests/ingestion/test_ticketmaster.py` | Tests for page-scrape fallback in adapter |
| Create | `backend/tests/db/test_visible_events_filter.py` | Unit tests for the filter helper |
| Create | `backend/tests/scripts/test_backfill_tm_descriptions.py` | Integration test for backfill script |
| Modify | `backend/tests/ingestion/test_scheduler.py` | Verify `embed_new_events` skips description-less events |
| Modify | `backend/tests/api/test_routes_events.py` | Verify list endpoint hides description-less events; detail endpoint returns them |
| Modify | `backend/tests/agent/test_tools.py` | Verify `search_events` hides description-less events |

Note on `routes_calendar.py`: the calendar reads `SavedEvent JOIN Event WHERE SavedEvent.user_id = ?`. Per spec Part C, a user's saved events must stay visible. No change needed.

---

## Task 1 — Recon: capture a real ticketmaster.de event page and identify the description selector

**Files:**
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/ticketmaster_page_sample.html`

The description selector is not knowable from source alone. This task captures one real page as the fixture and records the selector for use in Task 2.

- [ ] **Step 1.1: Pick an event URL from the DB**

Run:

```
cd backend
python -c "import sqlite3; c=sqlite3.connect('event_tracker.db').cursor(); c.execute(\"SELECT id, title, source_url FROM events WHERE source='ticketmaster' LIMIT 5\"); [print(r) for r in c.fetchall()]"
```

Pick one row and note the `source_url`. Prefer a music event since they dominate the DB.

- [ ] **Step 1.2: Create the fixtures package marker**

Create `backend/tests/fixtures/__init__.py` as an empty file.

- [ ] **Step 1.3: Download the page HTML**

Run (replace `<URL>` with the chosen source_url):

```
python -c "
import httpx, pathlib
url = '<URL>'
r = httpx.get(url, headers={'User-Agent': 'EventTrackerBot/1.0'}, follow_redirects=True, timeout=15)
r.raise_for_status()
pathlib.Path('tests/fixtures/ticketmaster_page_sample.html').write_text(r.text, encoding='utf-8')
print('saved', len(r.text), 'chars, status', r.status_code)
"
```

Expected: prints a byte count and status 200. If the response is < 5000 chars it's likely a bot-detection stub — try a different event URL or add `follow_redirects=True`.

- [ ] **Step 1.4: Identify the description block**

Open `backend/tests/fixtures/ticketmaster_page_sample.html` in an editor. Search for a marketing-style description sentence you'd expect on the page — try candidate selectors in this order:

```
python -c "
from bs4 import BeautifulSoup
html = open('tests/fixtures/ticketmaster_page_sample.html', encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')
# Try 1: meta description
m = soup.find('meta', attrs={'name': 'description'})
print('META:', m.get('content') if m else None)
# Try 2: schema.org JSON-LD
import json
for s in soup.find_all('script', type='application/ld+json'):
    try:
        data = json.loads(s.string or '')
        if isinstance(data, list):
            data = data[0] if data else {}
        if data.get('@type') in ('Event', 'MusicEvent', 'TheaterEvent', 'SportsEvent'):
            print('JSONLD desc:', (data.get('description') or '')[:200])
    except Exception:
        pass
# Try 3: about-this-event style container
for sel in ['div.about-event', 'div.event-description', 'div.eds-text--content', '[data-testid*=description]']:
    for el in soup.select(sel):
        print(f'SEL {sel}:', el.get_text(strip=True)[:200])
"
```

Record which selector produced the description. **Decision rule:** prefer JSON-LD (`<script type="application/ld+json">` with `@type` = `Event` / `MusicEvent` / `TheaterEvent` / `SportsEvent`, and a `description` field) if present — it's structured data and less likely to change. Fall back to `<meta name="description">` if not.

- [ ] **Step 1.5: Commit the fixture**

```
git add backend/tests/fixtures/__init__.py backend/tests/fixtures/ticketmaster_page_sample.html
git commit -m "test(fixtures): capture real ticketmaster.de event page for description extraction"
```

- [ ] **Step 1.6: Record the selector decision**

Note it here as a comment in your session notes; Task 2 hardcodes it. If JSON-LD was present with description text, Task 2 uses JSON-LD-first with meta-description fallback. If only meta-description was present, Task 2 uses meta-only.

---

## Task 2 — Pure extractor: `ticketmaster_page.extract_description`

**Files:**
- Create: `backend/app/ingestion/ticketmaster_page.py`
- Create: `backend/tests/ingestion/test_ticketmaster_page.py`

Pure function that takes an HTML string and returns `str | None`. No I/O.

- [ ] **Step 2.1: Write the failing tests**

Create `backend/tests/ingestion/test_ticketmaster_page.py`:

```python
from pathlib import Path

from app.ingestion.ticketmaster_page import extract_description

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "ticketmaster_page_sample.html"


def test_extract_description_from_real_fixture():
    html = _FIXTURE.read_text(encoding="utf-8")
    desc = extract_description(html)
    assert desc is not None
    assert len(desc) >= 20  # real pages have substantive text


def test_extract_description_prefers_jsonld_over_meta():
    html = """
    <html><head>
      <meta name="description" content="Meta fallback text.">
      <script type="application/ld+json">
      {"@type": "Event", "description": "JSON-LD primary text."}
      </script>
    </head><body></body></html>
    """
    assert extract_description(html) == "JSON-LD primary text."


def test_extract_description_falls_back_to_meta():
    html = """
    <html><head>
      <meta name="description" content="Meta fallback text.">
    </head><body></body></html>
    """
    assert extract_description(html) == "Meta fallback text."


def test_extract_description_handles_jsonld_list():
    html = """
    <html><head>
      <script type="application/ld+json">
      [{"@type": "Event", "description": "First item."}]
      </script>
    </head></html>
    """
    assert extract_description(html) == "First item."


def test_extract_description_ignores_non_event_jsonld():
    html = """
    <html><head>
      <meta name="description" content="From meta.">
      <script type="application/ld+json">
      {"@type": "Organization", "description": "Ignored."}
      </script>
    </head></html>
    """
    assert extract_description(html) == "From meta."


def test_extract_description_returns_none_when_absent():
    html = "<html><head></head><body>no description here</body></html>"
    assert extract_description(html) is None


def test_extract_description_returns_none_on_empty_string_desc():
    html = """
    <html><head>
      <script type="application/ld+json">{"@type": "Event", "description": ""}</script>
    </head></html>
    """
    assert extract_description(html) is None


def test_extract_description_survives_malformed_jsonld():
    html = """
    <html><head>
      <meta name="description" content="Meta wins when JSON-LD is broken.">
      <script type="application/ld+json">{ not valid json</script>
    </head></html>
    """
    assert extract_description(html) == "Meta wins when JSON-LD is broken."
```

- [ ] **Step 2.2: Run tests to confirm they fail**

Run:

```
cd backend
python -m pytest tests/ingestion/test_ticketmaster_page.py -v
```

Expected: all 8 tests FAIL (module doesn't exist).

- [ ] **Step 2.3: Implement the extractor**

Create `backend/app/ingestion/ticketmaster_page.py`:

```python
"""Extract description text from a ticketmaster.de event page.

Prefers structured schema.org JSON-LD (`@type` ∈ Event/MusicEvent/TheaterEvent/
SportsEvent) because it is the field that page templates render deterministically.
Falls back to the `<meta name="description">` tag."""
import json
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EVENT_TYPES = {"Event", "MusicEvent", "TheaterEvent", "SportsEvent"}


def _from_jsonld(soup: BeautifulSoup) -> str | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") not in _EVENT_TYPES:
                continue
            desc = entry.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
    return None


def _from_meta(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"name": "description"})
    if tag is None:
        return None
    content = tag.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def extract_description(html: str) -> str | None:
    """Return the event description from a ticketmaster.de event page, or None."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return _from_jsonld(soup) or _from_meta(soup)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run:

```
python -m pytest tests/ingestion/test_ticketmaster_page.py -v
```

Expected: all 8 tests PASS. If `test_extract_description_from_real_fixture` fails but the synthetic tests pass, the real page uses neither JSON-LD nor meta — go back to Task 1 Step 1.4, find the actual selector, and extend `extract_description` (and add a corresponding synthetic test).

- [ ] **Step 2.5: Commit**

```
git add backend/app/ingestion/ticketmaster_page.py backend/tests/ingestion/test_ticketmaster_page.py
git commit -m "feat(ticketmaster): add page-HTML description extractor"
```

---

## Task 3 — Wire the page-scrape fallback into `TicketmasterAdapter`

**Files:**
- Modify: `backend/app/ingestion/ticketmaster.py`
- Modify: `backend/tests/ingestion/test_ticketmaster.py`

Add `_fetch_page_description(source_url)` and extend the `_parse` fallback chain. Adds one HTTP request per event that lacks a description after the detail-endpoint check.

- [ ] **Step 3.1: Write failing tests for the page-scrape fallback**

Append to `backend/tests/ingestion/test_ticketmaster.py`:

```python
_PAGE_HTML_WITH_DESC = """
<html><head>
  <script type="application/ld+json">
  {"@type": "Event", "description": "From ticketmaster.de page."}
  </script>
</head></html>
"""

_PAGE_HTML_NO_DESC = "<html><head></head><body></body></html>"


class _FakeClientWithPages:
    """URL-aware fake supporting list JSON, detail JSON, and ticketmaster.de page HTML."""

    def __init__(self, list_pages, detail_map=None, page_map=None):
        self._list_iter = iter(list_pages)
        self._detail_map = detail_map or {}
        self._page_map = page_map or {}
        self.page_calls: list[str] = []

    def get(self, url: str, **kwargs) -> httpx.Response:
        if url.endswith("/events.json"):
            data = next(self._list_iter)
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        if "app.ticketmaster.com" in url:
            event_id = url.rsplit("/", 1)[-1].removesuffix(".json")
            data = self._detail_map.get(event_id, {})
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        # Otherwise it's a ticketmaster.de page URL.
        self.page_calls.append(url)
        html = self._page_map.get(url, "")
        status = 200 if url in self._page_map else 404
        return httpx.Response(status, text=html, request=httpx.Request("GET", url))


def test_description_from_ticketmaster_de_page_when_detail_empty():
    client = _FakeClientWithPages(
        [_SINGLE_PAGE],
        detail_map={},
        page_map={_EVENT_1["url"]: _PAGE_HTML_WITH_DESC},
    )
    adapter = TicketmasterAdapter(client=client)
    events = list(adapter.fetch())
    assert events[0].description == "From ticketmaster.de page."
    assert client.page_calls == [_EVENT_1["url"]]


def test_page_scrape_not_called_when_detail_has_description():
    client = _FakeClientWithPages(
        [_SINGLE_PAGE],
        detail_map={"tm_001": _DETAIL_WITH_INFO},
        page_map={_EVENT_1["url"]: _PAGE_HTML_WITH_DESC},
    )
    adapter = TicketmasterAdapter(client=client)
    events = list(adapter.fetch())
    assert events[0].description == "An evening of hard rock classics."
    assert client.page_calls == []


def test_description_none_when_page_scrape_finds_nothing():
    client = _FakeClientWithPages(
        [_SINGLE_PAGE],
        detail_map={},
        page_map={_EVENT_1["url"]: _PAGE_HTML_NO_DESC},
    )
    adapter = TicketmasterAdapter(client=client)
    events = list(adapter.fetch())
    assert events[0].description is None


def test_description_none_when_page_scrape_http_error():
    client = _FakeClientWithPages(
        [_SINGLE_PAGE],
        detail_map={},
        page_map={},  # 404 for any page URL
    )
    adapter = TicketmasterAdapter(client=client)
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].description is None
```

- [ ] **Step 3.2: Run new tests to confirm they fail**

Run:

```
python -m pytest tests/ingestion/test_ticketmaster.py::test_description_from_ticketmaster_de_page_when_detail_empty \
    tests/ingestion/test_ticketmaster.py::test_page_scrape_not_called_when_detail_has_description \
    tests/ingestion/test_ticketmaster.py::test_description_none_when_page_scrape_finds_nothing \
    tests/ingestion/test_ticketmaster.py::test_description_none_when_page_scrape_http_error -v
```

Expected: 4 FAIL.

Note: the first test using `_FakeClientWithPages` will surface a signature mismatch on `_FakeClient` if used incorrectly. The tests use a NEW class `_FakeClientWithPages`, so existing tests using `_FakeClient` are unaffected.

- [ ] **Step 3.3: Implement the fallback in the adapter**

Replace the `_parse` method and add `_fetch_page_description` in `backend/app/ingestion/ticketmaster.py`. After the existing `_fetch_detail` method (around line 96), insert:

```python
    def _fetch_page_description(self, source_url: str) -> str | None:
        """Fallback: scrape the public ticketmaster.de event page."""
        if not source_url:
            return None
        try:
            resp = self._client.get(source_url)
            resp.raise_for_status()
        except Exception:
            logger.warning("TM page-scrape failed for %s", source_url)
            return None
        from app.ingestion.ticketmaster_page import extract_description
        return extract_description(resp.text)
```

Then modify `_parse` to extend the fallback chain. Replace the description-computation block (currently lines 113-117):

```python
            description: str | None = None
            if detail:
                description = (
                    detail.get("info") or detail.get("additionalInfo") or detail.get("pleaseNote")
                ) or None
```

with:

```python
            description: str | None = None
            if detail:
                description = (
                    detail.get("info") or detail.get("additionalInfo") or detail.get("pleaseNote")
                ) or None
            if not description:
                description = self._fetch_page_description(raw.get("url", ""))
```

- [ ] **Step 3.4: Run all TM tests**

Run:

```
python -m pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all previously-passing tests still pass; 4 new tests now pass. Total: 16 tests pass.

- [ ] **Step 3.5: Commit**

```
git add backend/app/ingestion/ticketmaster.py backend/tests/ingestion/test_ticketmaster.py
git commit -m "feat(ticketmaster): add page-scrape fallback for description"
```

---

## Task 4 — Add `visible_events_filter()` helper

**Files:**
- Modify: `backend/app/db/models/event.py`
- Create: `backend/tests/db/test_visible_events_filter.py`

One place to define "an event that should be shown to users": active and has a non-empty description.

- [ ] **Step 4.1: Write the failing tests**

Create `backend/tests/db/test_visible_events_filter.py`:

```python
from datetime import datetime, timezone

from app.db.models.event import Event, visible_events_filter


def _make(session, **overrides):
    base = dict(
        id="e0",
        external_id="ext0",
        source="ticketmaster",
        title="T",
        description="A real description.",
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music",
        tags=[],
        source_url="https://x/e",
        raw_data={},
    )
    base.update(overrides)
    ev = Event(**base)
    session.add(ev)
    session.commit()
    return ev


def test_filter_returns_only_active_with_description(db_session):
    _make(db_session, id="ok",       description="Real text.",  is_active=True)
    _make(db_session, id="empty",    description="",            is_active=True, external_id="e2")
    _make(db_session, id="null",     description=None,          is_active=True, external_id="e3")
    _make(db_session, id="inactive", description="Real text.",  is_active=False, external_id="e4")

    ids = {r.id for r in db_session.query(Event).filter(visible_events_filter()).all()}
    assert ids == {"ok"}


def test_filter_composes_with_other_filters(db_session):
    _make(db_session, id="music", category="music", description="A")
    _make(db_session, id="theater", category="theater", description="B", external_id="e2")
    _make(db_session, id="music_empty", category="music", description="", external_id="e3")

    ids = {
        r.id
        for r in db_session.query(Event)
        .filter(visible_events_filter())
        .filter(Event.category == "music")
        .all()
    }
    assert ids == {"music"}
```

- [ ] **Step 4.2: Run tests to confirm they fail**

Run:

```
python -m pytest tests/db/test_visible_events_filter.py -v
```

Expected: FAIL — `visible_events_filter` is not importable.

- [ ] **Step 4.3: Implement the helper**

Modify `backend/app/db/models/event.py`. Change the imports at the top:

```python
from sqlalchemy import JSON, Boolean, DateTime, Float, String, UniqueConstraint
```

to:

```python
from sqlalchemy import JSON, Boolean, DateTime, Float, String, UniqueConstraint, and_
```

Then append after the `Event` class:

```python
def visible_events_filter():
    """SQLAlchemy filter for user-facing event queries.

    Active AND has a non-empty description. Applied at every user-visible
    query site (list endpoint, agent tools, calendar recommendations, embedding
    feed) so events without descriptions never surface to the user."""
    return and_(
        Event.is_active == True,  # noqa: E712
        Event.description.isnot(None),
        Event.description != "",
    )
```

- [ ] **Step 4.4: Run tests**

Run:

```
python -m pytest tests/db/test_visible_events_filter.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 4.5: Commit**

```
git add backend/app/db/models/event.py backend/tests/db/test_visible_events_filter.py
git commit -m "feat(events): visible_events_filter helper for hiding no-description events"
```

---

## Task 5 — Apply filter to the list endpoint (`routes_events.py`)

**Files:**
- Modify: `backend/app/api/routes_events.py`
- Modify: `backend/tests/api/test_routes_events.py`

`list_events` (line 43) currently filters by `is_active == True`. Swap for `visible_events_filter()`. `get_event` (line 100) is deliberately unchanged per spec.

- [ ] **Step 5.0: Fix pre-existing fixture (would break after filter change)**

The `setup` fixture in `backend/tests/api/test_routes_events.py` creates Events without a `description` field, defaulting to `None`. After Step 5.3 they would vanish from the list feed and break `test_list_events_paginated`, `test_list_events_category_filter`, and `test_list_events_includes_user_context`.

In the `setup` fixture (around line 16), change the `Event(...)` construction inside the loop to include a description. The current block:

```python
    for i, cat in enumerate(["music", "tech", "music"]):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", category=cat, source_url="http://x",
            start_datetime=base + timedelta(days=i),
        ))
```

becomes:

```python
    for i, cat in enumerate(["music", "tech", "music"]):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", category=cat, source_url="http://x",
            description=f"Description for event {i}.",
            start_datetime=base + timedelta(days=i),
        ))
```

Also scan the rest of the file for any other test that seeds an Event without a description and relies on it appearing in list results. In `test_event_detail_calendar_kind_null_when_not_in_calendar` (around line 60), the event is fetched via `/events/{id}` (detail route, no filter change) — leave it alone.

Run the existing tests to confirm they still pass:

```
python -m pytest tests/api/test_routes_events.py -v
```

Expected: all still pass (fixture change is a no-op on current behavior).

- [ ] **Step 5.1: Add failing tests to `test_routes_events.py`**

Look at existing tests in `backend/tests/api/test_routes_events.py` to understand fixtures. Then add these two tests to that file (at the end):

```python
def test_list_events_hides_events_without_description(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event
    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(
            id="with_desc", external_id="a", source="ticketmaster",
            title="With desc", description="Real text.", start_datetime=now,
            category="music", tags=[], source_url="https://x/a", raw_data={},
        ),
        Event(
            id="no_desc", external_id="b", source="ticketmaster",
            title="No desc", description=None, start_datetime=now,
            category="music", tags=[], source_url="https://x/b", raw_data={},
        ),
        Event(
            id="empty_desc", external_id="c", source="ticketmaster",
            title="Empty desc", description="", start_datetime=now,
            category="music", tags=[], source_url="https://x/c", raw_data={},
        ),
    ])
    db_session.commit()

    resp = client.get("/events?date_from=2026-07-15&date_to=2026-07-16")
    assert resp.status_code == 200
    data = resp.json()
    ids = {e["id"] for e in data["events"]}
    assert ids == {"with_desc"}
    assert data["total"] == 1


def test_get_event_returns_event_even_without_description(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event
    db_session.add(Event(
        id="no_desc_direct", external_id="d", source="ticketmaster",
        title="Direct fetch", description=None,
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music", tags=[], source_url="https://x/d", raw_data={},
    ))
    db_session.commit()

    resp = client.get("/events/no_desc_direct")
    assert resp.status_code == 200
    assert resp.json()["id"] == "no_desc_direct"
```

- [ ] **Step 5.2: Run tests to confirm they fail**

Run:

```
python -m pytest tests/api/test_routes_events.py::test_list_events_hides_events_without_description \
    tests/api/test_routes_events.py::test_get_event_returns_event_even_without_description -v
```

Expected: the first test FAILS (no_desc + empty_desc leak through); the second passes if no code changes are needed for detail (should already pass).

- [ ] **Step 5.3: Change the list endpoint filter**

In `backend/app/api/routes_events.py`, add the import at the top (after existing imports from `app.db.models`):

```python
from app.db.models.event import visible_events_filter
```

Then replace line 43:

```python
    qry = db.query(Event).filter(Event.is_active == True)  # noqa: E712
```

with:

```python
    qry = db.query(Event).filter(visible_events_filter())
```

- [ ] **Step 5.4: Run tests**

Run:

```
python -m pytest tests/api/test_routes_events.py -v
```

Expected: all tests pass (both new ones + all previously-passing).

- [ ] **Step 5.5: Commit**

```
git add backend/app/api/routes_events.py backend/tests/api/test_routes_events.py
git commit -m "feat(events): hide events without description from list endpoint"
```

---

## Task 6 — Apply filter to agent tools (`search_events`, `get_recommendations`)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/tests/agent/test_tools.py`

`search_events` (line 83) and the id-hydration inside `get_recommendations` (line 300).

- [ ] **Step 6.0: Fix pre-existing fixtures (would break after filter change)**

Three existing tests in `backend/tests/agent/test_tools.py` seed Events with `description=""` and expect them to appear in `search_events` results. After Step 6.3 they would be filtered out and the tests would fail.

Change `description=""` to a non-empty string in each of these tests:

- `test_search_events_defaults_to_today_plus_3d` (around lines 223 and 228): `description=""` → `description="Real."`
- `test_search_events_explicit_bounds_override_default` (around line 247): `description=""` → `description="Real."`
- `test_search_events_one_bound_does_not_trigger_default` (around line 267): `description=""` → `description="Real."`

Also scan the file for the `user` fixture and the top-of-file setup (around lines 22 and 29 already use real descriptions — leave them alone).

Run existing tests to confirm they still pass:

```
python -m pytest tests/agent/test_tools.py -v
```

Expected: all still pass.

- [ ] **Step 6.1: Add failing test for `search_events`**

Add to `backend/tests/agent/test_tools.py` (at the end). First check the existing test patterns — most use `_session_factory` monkeypatched to return the fixture session. Follow that pattern:

```python
def test_search_events_hides_no_description(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.agent import tools

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(
            id="visible", external_id="a", source="ticketmaster", title="Yes",
            description="Real.", start_datetime=now, category="music",
            tags=[], source_url="https://x/a", raw_data={},
        ),
        Event(
            id="hidden", external_id="b", source="ticketmaster", title="No",
            description=None, start_datetime=now, category="music",
            tags=[], source_url="https://x/b", raw_data={},
        ),
    ])
    db_session.commit()

    rows = tools.search_events.invoke({
        "date_from": "2026-07-15",
        "date_to": "2026-07-16",
    })
    ids = {r["id"] for r in rows}
    assert ids == {"visible"}
```

- [ ] **Step 6.2: Run test to confirm it fails**

Run:

```
python -m pytest tests/agent/test_tools.py::test_search_events_hides_no_description -v
```

Expected: FAIL — `hidden` leaks through.

- [ ] **Step 6.3: Change `search_events` and `get_recommendations`**

In `backend/app/agent/tools.py`, add to the imports (after existing model imports):

```python
from app.db.models.event import visible_events_filter
```

Change line 83 from:

```python
        q = session.query(Event).filter(Event.is_active == True)  # noqa: E712
```

to:

```python
        q = session.query(Event).filter(visible_events_filter())
```

Change line 300 (inside `get_recommendations`) from:

```python
        rows = session.query(Event).filter(Event.id.in_(id_to_score.keys())).all()
```

to:

```python
        rows = (
            session.query(Event)
            .filter(Event.id.in_(id_to_score.keys()))
            .filter(visible_events_filter())
            .all()
        )
```

Do NOT change `get_calendar` (lines 116-119): saved events must stay visible per spec.
Do NOT change existence checks at lines 136 and 324: they only verify the row exists.

- [ ] **Step 6.4: Run tests**

Run:

```
python -m pytest tests/agent/test_tools.py -v
```

Expected: all tests pass.

- [ ] **Step 6.5: Commit**

```
git add backend/app/agent/tools.py backend/tests/agent/test_tools.py
git commit -m "feat(agent): hide events without description from search and recommend"
```

---

## Task 7 — Apply filter to the embedding feed (`scheduler.embed_new_events`)

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

Two changes: only embed events matching `visible_events_filter()`, and update the stale-sweep keep-set to match — so Chroma never contains vectors for hidden events.

- [ ] **Step 7.1: Inspect existing scheduler tests**

Run:

```
python -m pytest tests/ingestion/test_scheduler.py -v --collect-only
```

This lists existing tests. The next step adds a new one that must follow the same fixture pattern (likely `db_session` + mocking `chroma_upsert_events`).

- [ ] **Step 7.2: Add failing test**

Read the top of `backend/tests/ingestion/test_scheduler.py` for the existing import/mocking pattern. Then append this test. Adjust the mocked module path if Step 7.1 shows a different pattern (e.g., `app.rag.chroma_store.upsert_events` vs `app.ingestion.scheduler.chroma_upsert_events`).

```python
def test_embed_new_events_skips_events_without_description(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.ingestion import scheduler

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(
            id="with_desc", external_id="a", source="ticketmaster", title="A",
            description="Real.", start_datetime=now, category="music",
            tags=[], source_url="https://x/a", raw_data={},
        ),
        Event(
            id="no_desc", external_id="b", source="ticketmaster", title="B",
            description=None, start_datetime=now, category="music",
            tags=[], source_url="https://x/b", raw_data={},
        ),
    ])
    db_session.commit()

    calls: dict = {"upserted": None, "deleted": None}

    def fake_upsert(payload):
        calls["upserted"] = [p.id for p in payload]

    def fake_all_ids():
        return set()

    def fake_delete(ids):
        calls["deleted"] = list(ids)

    monkeypatch.setattr(scheduler, "chroma_upsert_events", fake_upsert)
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", fake_all_ids)
    monkeypatch.setattr(scheduler.chroma_store, "delete_by_ids", fake_delete)

    scheduler.embed_new_events(db_session)

    assert calls["upserted"] == ["with_desc"]


def test_embed_new_events_purges_no_description_from_chroma(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.ingestion import scheduler

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add(Event(
        id="no_desc", external_id="b", source="ticketmaster", title="B",
        description=None, start_datetime=now, category="music",
        tags=[], source_url="https://x/b", raw_data={},
    ))
    db_session.commit()

    calls: dict = {"deleted": []}

    monkeypatch.setattr(scheduler, "chroma_upsert_events", lambda payload: None)
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", lambda: {"no_desc", "gone"})
    monkeypatch.setattr(
        scheduler.chroma_store,
        "delete_by_ids",
        lambda ids: calls["deleted"].extend(ids),
    )

    scheduler.embed_new_events(db_session)

    # Both "gone" (not in DB) and "no_desc" (in DB but hidden) must be purged.
    assert set(calls["deleted"]) == {"no_desc", "gone"}
```

- [ ] **Step 7.3: Run tests to confirm they fail**

Run:

```
python -m pytest tests/ingestion/test_scheduler.py::test_embed_new_events_skips_events_without_description \
    tests/ingestion/test_scheduler.py::test_embed_new_events_purges_no_description_from_chroma -v
```

Expected: 2 FAIL.

- [ ] **Step 7.4: Implement**

In `backend/app/ingestion/scheduler.py`, add the import (after existing `Event` import):

```python
from app.db.models.event import visible_events_filter
```

Replace the `embed_new_events` function body. Current version (lines 20-51):

```python
def embed_new_events(session: Session) -> None:
    """Embed all currently-active events into Chroma and drop stale vectors.

    Stale = a Chroma id that no longer exists in the events table. Without
    this sweep, wiping event_tracker.db (or any other event-removal path)
    leaves orphan vectors that outrank live ones in get_recommendations and
    cause the tool to return an empty list after the SQL hydration step.
    Idempotent: upsert by id, delete by id."""
    all_event_ids = {row[0] for row in session.query(Event.id).all()}
    stale = list(chroma_store.all_ids() - all_event_ids)
    if stale:
        chroma_store.delete_by_ids(stale)
        logger.info("embed_new_events: purged %d stale Chroma vector(s)", len(stale))

    rows = session.query(Event).filter(Event.is_active == True).all()  # noqa: E712
    ...
```

Replace with:

```python
def embed_new_events(session: Session) -> None:
    """Embed all currently-visible events into Chroma and drop stale vectors.

    Stale = a Chroma id whose event no longer passes visible_events_filter()
    (deleted, deactivated, or missing a description). Idempotent."""
    visible_ids = {
        row[0]
        for row in session.query(Event.id).filter(visible_events_filter()).all()
    }
    stale = list(chroma_store.all_ids() - visible_ids)
    if stale:
        chroma_store.delete_by_ids(stale)
        logger.info("embed_new_events: purged %d stale Chroma vector(s)", len(stale))

    rows = session.query(Event).filter(visible_events_filter()).all()
    if not rows:
        logger.info("embed_new_events: no visible events")
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

- [ ] **Step 7.5: Run tests**

Run:

```
python -m pytest tests/ingestion/test_scheduler.py -v
```

Expected: all tests pass.

- [ ] **Step 7.6: Commit**

```
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): embed only visible events and purge stale vectors"
```

---

## Task 8 — Backfill script for existing DB rows

**Files:**
- Create: `backend/scripts/backfill_tm_descriptions.py`
- Create: `backend/tests/scripts/test_backfill_tm_descriptions.py`

Walks all existing Ticketmaster events with missing descriptions and applies the same extractor.

- [ ] **Step 8.1: Write the failing test**

Create `backend/tests/scripts/test_backfill_tm_descriptions.py`:

```python
from datetime import datetime, timezone

import httpx

from app.db.models import Event
from scripts import backfill_tm_descriptions


class _FakeClient:
    def __init__(self, page_map):
        self._page_map = page_map
        self.calls: list[str] = []

    def get(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append(url)
        if url not in self._page_map:
            return httpx.Response(404, request=httpx.Request("GET", url))
        return httpx.Response(200, text=self._page_map[url], request=httpx.Request("GET", url))


def _seed(session, id_: str, description, source_url: str, source: str = "ticketmaster"):
    session.add(Event(
        id=id_, external_id=id_, source=source, title="T",
        description=description,
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music", tags=[], source_url=source_url, raw_data={},
    ))
    session.commit()


_HTML_OK = """
<html><head>
  <script type="application/ld+json">{"@type": "Event", "description": "Backfilled text."}</script>
</head></html>
"""


def test_backfill_updates_missing_descriptions(db_session):
    _seed(db_session, "e1", None, "https://ticketmaster.de/e1")
    _seed(db_session, "e2", "", "https://ticketmaster.de/e2")
    _seed(db_session, "e3", "Already has one.", "https://ticketmaster.de/e3")
    _seed(db_session, "e4", None, "https://ticketmaster.de/e4", source="eventbrite")

    client = _FakeClient({
        "https://ticketmaster.de/e1": _HTML_OK,
        "https://ticketmaster.de/e2": _HTML_OK,
        # e4 also has HTML available, but it's not TM so must not be visited
        "https://ticketmaster.de/e4": _HTML_OK,
    })
    report = backfill_tm_descriptions.run(db_session, client=client, delay=0.0)

    assert report["scanned"] == 2   # e1, e2
    assert report["updated"] == 2
    assert report["failed"] == 0
    assert {c for c in client.calls} == {
        "https://ticketmaster.de/e1",
        "https://ticketmaster.de/e2",
    }
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description == "Backfilled text."
    assert db_session.query(Event).filter_by(id="e2").one().description == "Backfilled text."
    # Untouched:
    assert db_session.query(Event).filter_by(id="e3").one().description == "Already has one."
    assert db_session.query(Event).filter_by(id="e4").one().description is None


def test_backfill_handles_http_errors(db_session):
    _seed(db_session, "e1", None, "https://ticketmaster.de/e1")

    client = _FakeClient({})  # all fetches 404
    report = backfill_tm_descriptions.run(db_session, client=client, delay=0.0)

    assert report["scanned"] == 1
    assert report["updated"] == 0
    assert report["failed"] == 1
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description is None


def test_backfill_is_idempotent(db_session):
    _seed(db_session, "e1", None, "https://ticketmaster.de/e1")
    client = _FakeClient({"https://ticketmaster.de/e1": _HTML_OK})

    first = backfill_tm_descriptions.run(db_session, client=client, delay=0.0)
    second = backfill_tm_descriptions.run(db_session, client=client, delay=0.0)

    assert first["updated"] == 1
    assert second["scanned"] == 0  # already has description on re-run
    assert second["updated"] == 0
```

- [ ] **Step 8.2: Run tests to confirm they fail**

Run:

```
python -m pytest tests/scripts/test_backfill_tm_descriptions.py -v
```

Expected: FAIL — module `scripts.backfill_tm_descriptions` does not exist.

- [ ] **Step 8.3: Implement the script**

Create `backend/scripts/backfill_tm_descriptions.py`:

```python
"""Backfill missing description for existing Ticketmaster events.

Iterates every event row where source='ticketmaster' AND description is
null or empty, fetches its public ticketmaster.de source_url, extracts the
description via app.ingestion.ticketmaster_page.extract_description, and
writes the result back. Idempotent: re-running only touches rows that are
still without a description.

Usage from backend/:  python -m scripts.backfill_tm_descriptions
"""
from __future__ import annotations

import logging
import sys
import time

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.session import SessionLocal
from app.ingestion.ticketmaster_page import extract_description

logger = logging.getLogger(__name__)

_DEFAULT_DELAY = 0.2  # seconds between page fetches — matches ingestion adapter
_USER_AGENT = "EventTrackerBot/1.0"


def _missing_desc_rows(session: Session) -> list[Event]:
    return (
        session.query(Event)
        .filter(Event.source == "ticketmaster")
        .filter(or_(Event.description.is_(None), Event.description == ""))
        .all()
    )


def run(
    session: Session,
    client: httpx.Client | None = None,
    delay: float = _DEFAULT_DELAY,
) -> dict:
    """Backfill descriptions. Commits after every successful row.

    Returns a report dict: {scanned, updated, failed}.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=15, headers={"User-Agent": _USER_AGENT})

    rows = _missing_desc_rows(session)
    scanned = len(rows)
    updated = 0
    failed = 0

    logger.info("backfill: %d ticketmaster events missing description", scanned)

    try:
        for i, row in enumerate(rows, start=1):
            desc: str | None = None
            try:
                resp = client.get(row.source_url)
                resp.raise_for_status()
                desc = extract_description(resp.text)
            except Exception:
                logger.warning("backfill: fetch failed for %s (%s)", row.id, row.source_url)

            if desc:
                row.description = desc
                session.commit()
                updated += 1
            else:
                failed += 1

            if i % 25 == 0:
                logger.info("backfill: progress %d/%d (updated=%d)", i, scanned, updated)

            if delay > 0:
                time.sleep(delay)
    finally:
        if own_client:
            client.close()

    logger.info(
        "backfill complete — scanned=%d updated=%d failed=%d", scanned, updated, failed
    )
    return {"scanned": scanned, "updated": updated, "failed": failed}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        report = run(session)
    finally:
        session.close()
    print(
        f"scanned={report['scanned']} updated={report['updated']} failed={report['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8.4: Run tests**

Run:

```
python -m pytest tests/scripts/test_backfill_tm_descriptions.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 8.5: Commit**

```
git add backend/scripts/backfill_tm_descriptions.py backend/tests/scripts/test_backfill_tm_descriptions.py
git commit -m "feat(scripts): add Ticketmaster description backfill script"
```

---

## Task 9 — Full test-suite verification

- [ ] **Step 9.1: Run every backend test**

Run:

```
cd backend
python -m pytest -v
```

Expected: all tests pass. If any pre-existing test now fails, investigate — most likely a fixture that inserted an event with `description=None` and expected it to be visible. Fix by giving the seeded event a real description string.

- [ ] **Step 9.2: If green, commit no changes**

Nothing to commit if step 9.1 passed. If a test was updated, commit it separately with the fix.

---

## Task 10 — Run the backfill against the live DB (manual, network required)

This is a one-shot production run. Not automated in this plan — instructions here for the operator.

- [ ] **Step 10.1: Snapshot the DB**

```
cp backend/event_tracker.db backend/event_tracker.db.bak-2026-07-01
```

- [ ] **Step 10.2: Record coverage before**

```
python -c "
import sqlite3
c = sqlite3.connect('backend/event_tracker.db').cursor()
c.execute(\"SELECT source, COUNT(*), SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) FROM events GROUP BY source\")
for row in c.fetchall(): print(row)
"
```

Save output.

- [ ] **Step 10.3: Run the backfill**

```
cd backend
python -m scripts.backfill_tm_descriptions
```

Expected: logs progress every 25 events. Runs at ~5 events/sec (0.2s delay), so ~318 events → ~65s. Final line prints `scanned=... updated=... failed=...`.

- [ ] **Step 10.4: Record coverage after**

Same command as Step 10.2. Compare — expect updated ≥ 100 (well above the current 19). If updated is very low, the selector is likely wrong for a large chunk of pages; capture 2-3 failing HTML pages via the Task 1 recon script and expand `extract_description`.

- [ ] **Step 10.5: Re-embed and re-check**

Run:

```
python -c "
from app.db.session import SessionLocal
from app.ingestion.scheduler import embed_new_events
s = SessionLocal(); embed_new_events(s); s.close()
"
```

Expected: log lines showing purge count (should include the previously-embedded no-description events) and embed count.

---

## Notes for the executor

- **Line numbers in the file map are informational**: they are correct at plan-write time. If the file has since been edited, use the surrounding code context (function signatures, docstrings) to locate the change site.
- **Every commit contains a passing test suite for the code touched in that task**. Do not roll steps together.
- **If Task 1's fixture reveals no JSON-LD and no meta description**, stop and report — the whole strategy hinges on the fixture. Options: try another event URL, or extend `extract_description` with a page-specific CSS selector confirmed against the fixture.
