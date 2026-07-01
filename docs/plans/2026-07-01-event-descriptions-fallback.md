# Event Descriptions Fallback — TM Page Scrape + Hide-Empty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise Ticketmaster description coverage from 5.6% by scraping the public ticketmaster.de event page as a fallback source, backfill existing rows, and hide any events that still lack a description from every user-facing query.

**Architecture:** New shared module `app.ingestion.ticketmaster_page` provides one HTML-extraction function used by both (a) an inline fallback added to `TicketmasterAdapter._parse`, and (b) a one-off backfill script. A new `visible_events_filter()` helper in `app.db.models.event` is applied at every user-facing `Event` query site and to the Chroma embedding feed, so events without descriptions are hidden from the UI, agent, and vector store.

**Tech Stack:** Python 3.11, Playwright (headless Chromium), BeautifulSoup 4, SQLAlchemy 2.x, pytest.

**Spec:** `docs/specs/2026-07-01-event-descriptions-fallback-design.md`. **Note the "Amendment" section at the bottom** — the original httpx-based scrape was blocked by ticketmaster.de's JS challenge; Playwright is the chosen bypass.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `backend/pyproject.toml` | Add `playwright` dep |
| Create | `backend/app/ingestion/browser.py` | `PageFetcher` protocol + `PlaywrightPageFetcher` context manager |
| Create | `backend/app/ingestion/ticketmaster_page.py` | Pure HTML → description text extraction |
| Modify | `backend/app/ingestion/ticketmaster.py` | Add page-fetch fallback into `_parse` chain via injected `PageFetcher` |
| Modify | `backend/app/ingestion/scheduler.py` | Apply visible filter; wrap adapters with a `PlaywrightPageFetcher` for the run |
| Create | `backend/scripts/backfill_tm_descriptions.py` | One-off backfill using `PlaywrightPageFetcher` |
| Modify | `backend/app/db/models/event.py` | Add `visible_events_filter()` helper |
| Modify | `backend/app/api/routes_events.py` | Apply filter to list endpoint (leave detail route alone) |
| Modify | `backend/app/agent/tools.py` | Apply filter to `search_events`, `get_recommendations` |
| Create | `backend/tests/fixtures/__init__.py` | Empty package marker |
| Create | `backend/tests/fixtures/ticketmaster_page_sample.html` | Real rendered ticketmaster.de page HTML |
| Create | `backend/tests/ingestion/test_browser.py` | Smoke test for `PlaywrightPageFetcher` (marked slow, opt-in) |
| Create | `backend/tests/ingestion/test_ticketmaster_page.py` | Unit tests for `extract_description` |
| Modify | `backend/tests/ingestion/test_ticketmaster.py` | Tests for page-fetch fallback in adapter |
| Create | `backend/tests/db/test_visible_events_filter.py` | Unit tests for the filter helper |
| Create | `backend/tests/scripts/test_backfill_tm_descriptions.py` | Integration test for backfill script |
| Modify | `backend/tests/ingestion/test_scheduler.py` | Verify `embed_new_events` skips description-less events |
| Modify | `backend/tests/api/test_routes_events.py` | Verify list endpoint hides description-less events; detail endpoint returns them |
| Modify | `backend/tests/agent/test_tools.py` | Verify `search_events` hides description-less events |

Note on `routes_calendar.py`: the calendar reads `SavedEvent JOIN Event WHERE SavedEvent.user_id = ?`. Per spec Part C, a user's saved events must stay visible. No change needed.

---

## Task 0 — Install Playwright and Chromium

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 0.1: Add Playwright to `pyproject.toml`**

In `backend/pyproject.toml`, in the `dependencies` list, append after `"tldextract>=5.1.0",`:

```toml
    "playwright>=1.44.0",
```

- [ ] **Step 0.2: Install the package**

```
cd backend
pip install -e .
```

Expected: `playwright` installed. If pip is slow, `pip install playwright>=1.44.0` alone also works.

- [ ] **Step 0.3: Install the Chromium browser binary**

```
python -m playwright install chromium
```

Expected: downloads Chromium (~150 MB). Progress bar to completion.

- [ ] **Step 0.4: Smoke-test the browser**

```
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('https://example.com', timeout=15000)
    print('title:', page.title())
    b.close()
"
```

Expected: prints `title: Example Domain`.

- [ ] **Step 0.5: Commit**

```
git add backend/pyproject.toml
git commit -m "chore(deps): add playwright for ticketmaster.de page rendering"
```

---

## Task 1 — Recon: capture a real ticketmaster.de event page (via Playwright) and identify the description selector

**Files:**
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/ticketmaster_page_sample.html`

The description selector is not knowable from source alone. Use Playwright (installed in Task 0) to fetch a real rendered page and inspect it.

- [ ] **Step 1.1: Pick an event URL from the DB**

Run:

```
cd backend
python -c "import sqlite3; c=sqlite3.connect('event_tracker.db').cursor(); c.execute(\"SELECT id, title, source_url FROM events WHERE source='ticketmaster' LIMIT 5\"); [print(r) for r in c.fetchall()]"
```

Pick one row and note the `source_url`. Prefer a music event since they dominate the DB.

- [ ] **Step 1.2: Create the fixtures package marker**

Create `backend/tests/fixtures/__init__.py` as an empty file.

- [ ] **Step 1.3: Render the page with Playwright and save the HTML**

Run (replace `<URL>` with the chosen source_url):

```
python -c "
from playwright.sync_api import sync_playwright
import pathlib
url = '<URL>'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    page = ctx.new_page()
    page.goto(url, timeout=30000, wait_until='networkidle')
    # Additional wait for the challenge to clear if present.
    page.wait_for_timeout(2000)
    html = page.content()
    browser.close()
pathlib.Path('tests/fixtures/ticketmaster_page_sample.html').write_text(html, encoding='utf-8')
print('saved', len(html), 'chars')
"
```

Expected: prints `saved N chars` where N > 30000. If N is small (~6000), the challenge did not clear — try `wait_until='load'` and a longer `page.wait_for_timeout(5000)`.

- [ ] **Step 1.4: Identify the description block**

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

Record which selector produced the description. **Decision rule:** prefer JSON-LD if present (structured, less likely to change). Fall back to `<meta name="description">`.

- [ ] **Step 1.5: Commit the fixture**

```
git add backend/tests/fixtures/__init__.py backend/tests/fixtures/ticketmaster_page_sample.html
git commit -m "test(fixtures): capture real ticketmaster.de event page via playwright"
```

- [ ] **Step 1.6: Record the selector decision**

Report in your final message which selector was found. Task 2 hardcodes it. If both JSON-LD and meta are present, extractor tries JSON-LD first. If neither is present, escalate BLOCKED — the strategy hinges on this fixture.

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

## Task 3 — `PageFetcher` protocol + Playwright impl + wire into `TicketmasterAdapter`

**Files:**
- Create: `backend/app/ingestion/browser.py`
- Modify: `backend/app/ingestion/ticketmaster.py`
- Create: `backend/tests/ingestion/test_browser.py`
- Modify: `backend/tests/ingestion/test_ticketmaster.py`

Two moving parts: the `PageFetcher` abstraction (allows testing without a real browser) and the adapter wiring that calls it as a fallback.

- [ ] **Step 3.1: Create `browser.py` with the protocol and Playwright impl**

Create `backend/app/ingestion/browser.py`:

```python
"""Headless-browser page fetching for sites that block plain-HTTP clients.

`PageFetcher` is the interface adapters depend on. `PlaywrightPageFetcher`
is the concrete implementation using headless Chromium — used as a context
manager so the browser process is started once per ingestion run and
guaranteed to close on exit. Tests inject a fake `PageFetcher`."""
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_NAV_TIMEOUT_MS = 30000
_POST_NAV_WAIT_MS = 2000


class PageFetcher(Protocol):
    def fetch(self, url: str) -> str | None: ...


class PlaywrightPageFetcher:
    """Context-managed Playwright fetcher. Reuses one browser + context across calls.

    Usage:
        with PlaywrightPageFetcher() as fetcher:
            html = fetcher.fetch(url)
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=_USER_AGENT)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def fetch(self, url: str) -> str | None:
        if not url or self._context is None:
            return None
        page = self._context.new_page()
        try:
            page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="networkidle")
            page.wait_for_timeout(_POST_NAV_WAIT_MS)
            return page.content()
        except Exception:
            logger.warning("PlaywrightPageFetcher: fetch failed for %s", url)
            return None
        finally:
            page.close()
```

- [ ] **Step 3.2: Add an opt-in smoke test for the real browser**

Create `backend/tests/ingestion/test_browser.py`:

```python
"""Smoke test for PlaywrightPageFetcher. Requires network + `playwright install chromium`.

Marked `slow`: skipped by default. Run with `pytest -m slow` when validating."""
import pytest

from app.ingestion.browser import PlaywrightPageFetcher


@pytest.mark.slow
def test_playwright_fetcher_renders_example_com():
    with PlaywrightPageFetcher() as fetcher:
        html = fetcher.fetch("https://example.com")
    assert html is not None
    assert "Example Domain" in html


@pytest.mark.slow
def test_playwright_fetcher_returns_none_on_bad_url():
    with PlaywrightPageFetcher() as fetcher:
        html = fetcher.fetch("http://this-domain-does-not-resolve-abc123.invalid")
    assert html is None
```

Register the `slow` marker. Append to `backend/pyproject.toml`'s `[tool.pytest.ini_options]` section:

```toml
markers = [
    "slow: marks tests that require network / real browser (deselect with -m 'not slow')",
]
```

Update the default selection to skip slow tests: change:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-m 'not slow'"
markers = [
    "slow: marks tests that require network / real browser (deselect with -m 'not slow')",
]
```

- [ ] **Step 3.3: Write failing tests for the page-fetch fallback in the adapter**

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


class _FakePageFetcher:
    """Stand-in for PageFetcher — maps URL -> HTML, records calls."""

    def __init__(self, page_map: dict[str, str] | None = None):
        self._page_map = page_map or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.calls.append(url)
        return self._page_map.get(url)


def test_description_from_ticketmaster_de_page_when_detail_empty():
    fetcher = _FakePageFetcher({_EVENT_1["url"]: _PAGE_HTML_WITH_DESC})
    adapter = TicketmasterAdapter(
        client=_FakeClient([_SINGLE_PAGE]),
        page_fetcher=fetcher,
    )
    events = list(adapter.fetch())
    assert events[0].description == "From ticketmaster.de page."
    assert fetcher.calls == [_EVENT_1["url"]]


def test_page_fetch_not_called_when_detail_has_description():
    fetcher = _FakePageFetcher({_EVENT_1["url"]: _PAGE_HTML_WITH_DESC})
    adapter = TicketmasterAdapter(
        client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_INFO}),
        page_fetcher=fetcher,
    )
    events = list(adapter.fetch())
    assert events[0].description == "An evening of hard rock classics."
    assert fetcher.calls == []


def test_description_none_when_page_fetch_returns_no_description_content():
    fetcher = _FakePageFetcher({_EVENT_1["url"]: _PAGE_HTML_NO_DESC})
    adapter = TicketmasterAdapter(
        client=_FakeClient([_SINGLE_PAGE]),
        page_fetcher=fetcher,
    )
    events = list(adapter.fetch())
    assert events[0].description is None


def test_description_none_when_page_fetcher_returns_none():
    fetcher = _FakePageFetcher()  # returns None for any url
    adapter = TicketmasterAdapter(
        client=_FakeClient([_SINGLE_PAGE]),
        page_fetcher=fetcher,
    )
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].description is None


def test_no_page_fetch_when_page_fetcher_is_none():
    """Existing default behavior — adapter without page_fetcher does not error."""
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE]))
    events = list(adapter.fetch())
    assert events[0].description is None
```

- [ ] **Step 3.4: Run new tests to confirm they fail**

```
cd backend
python -m pytest tests/ingestion/test_ticketmaster.py -k "page_fetch or ticketmaster_de_page or fetcher_returns_none or fetcher_is_none" -v
```

Expected: FAIL — `TicketmasterAdapter.__init__` does not accept `page_fetcher`.

- [ ] **Step 3.5: Implement the adapter changes**

In `backend/app/ingestion/ticketmaster.py`:

Add to top imports:

```python
from app.ingestion.browser import PageFetcher
from app.ingestion.ticketmaster_page import extract_description
```

Change `TicketmasterAdapter.__init__` from:

```python
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key
```

to:

```python
    def __init__(
        self,
        client: httpx.Client | None = None,
        page_fetcher: PageFetcher | None = None,
    ):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key
        self._page_fetcher = page_fetcher
```

Add a new method after `_fetch_detail`:

```python
    def _fetch_page_description(self, source_url: str) -> str | None:
        """Fallback: fetch the public ticketmaster.de event page via the injected
        PageFetcher and extract its description."""
        if not source_url or self._page_fetcher is None:
            return None
        html = self._page_fetcher.fetch(source_url)
        if not html:
            return None
        return extract_description(html)
```

Replace the description-computation block in `_parse` (currently lines 113-117):

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

- [ ] **Step 3.6: Run all TM adapter tests**

```
python -m pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all previously-passing tests still pass; 5 new tests now pass.

- [ ] **Step 3.7: Commit**

```
git add backend/app/ingestion/browser.py backend/app/ingestion/ticketmaster.py backend/tests/ingestion/test_browser.py backend/tests/ingestion/test_ticketmaster.py backend/pyproject.toml
git commit -m "feat(ticketmaster): page-fetch fallback via injected PageFetcher (playwright impl)"
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

## Task 7 — Apply visible filter to embedding feed AND wire `PlaywrightPageFetcher` into ingestion

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

Three changes to `scheduler.py`:
1. Only embed events matching `visible_events_filter()`.
2. Update the stale-sweep keep-set to match (so Chroma never contains vectors for hidden events).
3. Wrap the ingestion loop in a `PlaywrightPageFetcher` context manager and pass the fetcher into `TicketmasterAdapter`.

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

- [ ] **Step 7.4: Implement embedding-filter changes**

In `backend/app/ingestion/scheduler.py`, add the imports (after existing `Event` import):

```python
from app.db.models.event import visible_events_filter
from app.ingestion.browser import PlaywrightPageFetcher
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

- [ ] **Step 7.5: Wire PlaywrightPageFetcher into `run_ingestion`**

Change `_default_adapters()` (line 54-55) from:

```python
def _default_adapters() -> list[SourceAdapter]:
    return [TicketmasterAdapter(), HamburgScraper()]
```

to accept a page fetcher:

```python
def _default_adapters(page_fetcher=None) -> list[SourceAdapter]:
    return [TicketmasterAdapter(page_fetcher=page_fetcher), HamburgScraper()]
```

Change `run_ingestion` body. Find the section (around line 71-83):

```python
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
```

Change the `if adapters is None:` block above it (around line 63-64) from:

```python
    if adapters is None:
        adapters = _default_adapters()
```

to leave that unset and wrap the fetch loop in the page fetcher. The full new `run_ingestion` body block becomes:

```python
    own_session = session is None
    if own_session:
        run_migrations()
        session = SessionLocal()

    try:
        with PlaywrightPageFetcher() as page_fetcher:
            active_adapters = adapters if adapters is not None else _default_adapters(page_fetcher=page_fetcher)

            all_events = []
            for adapter in active_adapters:
                try:
                    batch = list(adapter.fetch())
                    all_events.extend(batch)
                    logger.info("%s: fetched %d events", adapter.name, len(batch))
                except Exception:
                    logger.exception("%s: fetch failed, skipping", adapter.name)

        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        embed_new_events(session)
```

Rationale: adapters passed by tests already have their own fetcher (or none) — respect the injection. When called with no `adapters` argument (production), we build the default with the browser attached, and close the browser as soon as the fetch loop finishes.

- [ ] **Step 7.6: Add a test that adapters injection still works and does NOT start Playwright**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
def test_run_ingestion_with_explicit_adapters_does_not_start_playwright(db_session, monkeypatch):
    """When tests inject adapters, run_ingestion must not touch Playwright."""
    from app.ingestion import scheduler

    started = {"count": 0}

    class _Sentinel:
        def __enter__(self):
            started["count"] += 1
            raise AssertionError("Playwright should not start when adapters are injected")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scheduler, "PlaywrightPageFetcher", _Sentinel)

    # With adapters=[_OkAdapter()], PlaywrightPageFetcher context manager is still
    # entered (it wraps the whole fetch loop) — but the adapters passed in do not
    # need it. The current design DOES enter the context manager. To make this
    # opt-out for tests, `run_ingestion` should skip the context entirely when
    # `adapters is not None`.
    # (This test drives that requirement.)
    scheduler.run_ingestion(adapters=[_OkAdapter()], session=db_session)
    assert started["count"] == 0
```

This test exposes the fact that even with injected adapters, the current `run_ingestion` enters the Playwright context. To make the test pass, rewrite the `try:` block to only enter the context manager when adapters are default:

```python
    try:
        if adapters is None:
            with PlaywrightPageFetcher() as page_fetcher:
                active_adapters = _default_adapters(page_fetcher=page_fetcher)
                all_events = _fetch_all(active_adapters)
        else:
            all_events = _fetch_all(adapters)

        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        embed_new_events(session)
```

Where `_fetch_all` is a small helper (extract from the loop):

```python
def _fetch_all(adapters: list[SourceAdapter]) -> list:
    all_events = []
    for adapter in adapters:
        try:
            batch = list(adapter.fetch())
            all_events.extend(batch)
            logger.info("%s: fetched %d events", adapter.name, len(batch))
        except Exception:
            logger.exception("%s: fetch failed, skipping", adapter.name)
    return all_events
```

- [ ] **Step 7.7: Run tests**

```
python -m pytest tests/ingestion/test_scheduler.py -v
```

Expected: all tests pass, including the new no-Playwright-on-injection test.

- [ ] **Step 7.8: Commit**

```
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): visible-only embeddings + PlaywrightPageFetcher for prod ingest"
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

from app.db.models import Event
from scripts import backfill_tm_descriptions


class _FakePageFetcher:
    def __init__(self, page_map: dict[str, str]):
        self._page_map = page_map
        self.calls: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.calls.append(url)
        return self._page_map.get(url)


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

    fetcher = _FakePageFetcher({
        "https://ticketmaster.de/e1": _HTML_OK,
        "https://ticketmaster.de/e2": _HTML_OK,
        # e4 also has HTML available, but it's not TM so must not be visited
        "https://ticketmaster.de/e4": _HTML_OK,
    })
    report = backfill_tm_descriptions.run(db_session, page_fetcher=fetcher)

    assert report["scanned"] == 2   # e1, e2
    assert report["updated"] == 2
    assert report["failed"] == 0
    assert set(fetcher.calls) == {
        "https://ticketmaster.de/e1",
        "https://ticketmaster.de/e2",
    }
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description == "Backfilled text."
    assert db_session.query(Event).filter_by(id="e2").one().description == "Backfilled text."
    # Untouched:
    assert db_session.query(Event).filter_by(id="e3").one().description == "Already has one."
    assert db_session.query(Event).filter_by(id="e4").one().description is None


def test_backfill_handles_fetch_failures(db_session):
    _seed(db_session, "e1", None, "https://ticketmaster.de/e1")

    fetcher = _FakePageFetcher({})  # always returns None
    report = backfill_tm_descriptions.run(db_session, page_fetcher=fetcher)

    assert report["scanned"] == 1
    assert report["updated"] == 0
    assert report["failed"] == 1
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description is None


def test_backfill_is_idempotent(db_session):
    _seed(db_session, "e1", None, "https://ticketmaster.de/e1")
    fetcher = _FakePageFetcher({"https://ticketmaster.de/e1": _HTML_OK})

    first = backfill_tm_descriptions.run(db_session, page_fetcher=fetcher)
    second = backfill_tm_descriptions.run(db_session, page_fetcher=fetcher)

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
"""Backfill missing description for existing Ticketmaster events using Playwright.

Iterates every event row where source='ticketmaster' AND description is null
or empty, renders its public ticketmaster.de source_url via a headless-Chromium
PageFetcher, extracts the description with app.ingestion.ticketmaster_page.
extract_description, and writes the result back. Commits after every successful
row so partial progress is preserved. Idempotent: re-running only touches rows
that are still without a description.

Usage from backend/:  python -m scripts.backfill_tm_descriptions
"""
from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.session import SessionLocal
from app.ingestion.browser import PageFetcher, PlaywrightPageFetcher
from app.ingestion.ticketmaster_page import extract_description

logger = logging.getLogger(__name__)


def _missing_desc_rows(session: Session) -> list[Event]:
    return (
        session.query(Event)
        .filter(Event.source == "ticketmaster")
        .filter(or_(Event.description.is_(None), Event.description == ""))
        .all()
    )


def run(session: Session, page_fetcher: PageFetcher) -> dict:
    """Backfill descriptions. Commits after every successful row.

    Returns a report dict: {scanned, updated, failed}.
    """
    rows = _missing_desc_rows(session)
    scanned = len(rows)
    updated = 0
    failed = 0

    logger.info("backfill: %d ticketmaster events missing description", scanned)

    for i, row in enumerate(rows, start=1):
        html = page_fetcher.fetch(row.source_url)
        desc = extract_description(html) if html else None

        if desc:
            row.description = desc
            session.commit()
            updated += 1
        else:
            failed += 1

        if i % 25 == 0:
            logger.info("backfill: progress %d/%d (updated=%d)", i, scanned, updated)

    logger.info(
        "backfill complete — scanned=%d updated=%d failed=%d", scanned, updated, failed
    )
    return {"scanned": scanned, "updated": updated, "failed": failed}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        with PlaywrightPageFetcher() as fetcher:
            report = run(session, page_fetcher=fetcher)
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

Expected: logs progress every 25 events. Runs at ~1 event / 3–5 s (Playwright navigation + wait), so ~318 events → ~15–25 min. Final line prints `scanned=... updated=... failed=...`.

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
