# Event Descriptions Fallback — Wikipedia Enrichment + Hide-Empty Toggle (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise Ticketmaster description coverage from 5.6% by looking up each attraction's Wikipedia article (via `externalLinks.wiki`) and using the Wikipedia REST summary as the event description. Backfill existing rows. Add a config toggle to hide description-less events from every user-facing query (default: on).

**Architecture:** New shared module `app.ingestion.wikipedia` provides two pure functions (`wiki_title_from_url`, `extract_summary`) used by both (a) an inline fallback added to `TicketmasterAdapter._parse`, and (b) a one-off backfill script. A new `visible_events_filter()` helper in `app.db.models.event` reads `settings.hide_events_without_description` at call time and returns the strict or loose filter accordingly. Applied at every user-facing `Event` query site and to the Chroma embedding feed.

**Tech Stack:** Python 3.11, httpx (existing), BeautifulSoup 4 (existing, unused here), SQLAlchemy 2.x, pytest, Pydantic-Settings.

**Spec:** `docs/specs/2026-07-01-event-descriptions-fallback-design.md`. **Read "Amendment 2 (2026-07-03)" at the bottom** — it supersedes the original Part A and the Playwright Amendment 1. This plan v2 implements Amendment 2.

**History (do not implement, kept for context):** Original v1 tried a page scrape via httpx (blocked by Imperva), then Playwright (also blocked), then Playwright+stealth (worked technically but revealed ticketmaster.de has no editorial content on event pages). The pivot to Wikipedia enrichment is the surviving design.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `backend/pyproject.toml` | Remove `tf-playwright-stealth` (never used); keep `playwright` as-is for now |
| Modify | `backend/app/config.py` | Add `hide_events_without_description: bool = True` |
| Create | `backend/app/ingestion/wikipedia.py` | Pure funcs: `wiki_title_from_url`, `extract_summary` |
| Modify | `backend/app/ingestion/ticketmaster.py` | Add Wikipedia-lookup fallback into `_parse` chain; per-run cache |
| Modify | `backend/app/db/models/event.py` | Add `visible_events_filter()` helper (reads config at call time) |
| Modify | `backend/app/api/routes_events.py` | Apply filter to list endpoint (leave detail route alone) |
| Modify | `backend/app/agent/tools.py` | Apply filter to `search_events`, `get_recommendations` |
| Modify | `backend/app/ingestion/scheduler.py` | Apply visible filter to embedding feed + stale sweep |
| Create | `backend/scripts/backfill_tm_descriptions.py` | Iterate TM events missing description, lookup Wikipedia, commit |
| Create | `backend/tests/fixtures/__init__.py` | Empty package marker |
| Create | `backend/tests/fixtures/wiki_attraction_sample.json` | Real TM attraction detail JSON captured in Task 1 |
| Create | `backend/tests/fixtures/wiki_summary_sample.json` | Real Wikipedia REST summary JSON captured in Task 1 |
| Create | `backend/tests/ingestion/test_wikipedia.py` | Unit tests for pure functions |
| Modify | `backend/tests/ingestion/test_ticketmaster.py` | Tests for Wikipedia fallback in adapter |
| Create | `backend/tests/db/test_visible_events_filter.py` | Unit tests for filter helper — both toggle states |
| Create | `backend/tests/scripts/test_backfill_tm_descriptions.py` | Integration test for backfill script |
| Modify | `backend/tests/ingestion/test_scheduler.py` | Verify `embed_new_events` respects the filter |
| Modify | `backend/tests/api/test_routes_events.py` | Verify list endpoint hides no-desc events; detail endpoint returns them |
| Modify | `backend/tests/agent/test_tools.py` | Verify `search_events` hides no-desc events |

Note on `routes_calendar.py`: unchanged. Saved events must stay visible.

Note on `pyproject.toml`: `playwright` stays (already installed; no harm) — a follow-up cleanup PR can remove it. `tf-playwright-stealth` is not committed but is in `pyproject.toml`'s dep list — remove it in Task 0.

---

## Task 0 — Clean up dead Playwright/stealth dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 0.1: Remove `tf-playwright-stealth` from `pyproject.toml`**

Delete the line:

```toml
    "tf-playwright-stealth>=1.1.0",
```

Leave `playwright>=1.44.0` in place (already committed; removing is a follow-up).

- [ ] **Step 0.2: Reinstall to update lockfile / venv metadata**

```
cd backend
pip install -e .
```

- [ ] **Step 0.3: Commit**

```
git add backend/pyproject.toml
git commit -m "chore(deps): drop tf-playwright-stealth (Wikipedia pivot obviates it)"
```

---

## Task 1 — Recon: TM attraction wiki links + Wikipedia REST response

**Files:**
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/wiki_attraction_sample.json`
- Create: `backend/tests/fixtures/wiki_summary_sample.json`

Confirm two open questions before writing code:
1. **Do TM events already embed `_embedded.attractions[i].externalLinks.wiki`, or must we call `/attractions/{id}.json`?** This determines whether the adapter needs an extra API call per attraction.
2. **What does the Wikipedia REST summary response look like?** Shape the extractor to match.

- [ ] **Step 1.1: Pick 3 TM event IDs from the local DB**

```
cd backend
python -c "import sqlite3; c=sqlite3.connect('event_tracker.db').cursor(); c.execute(\"SELECT id, external_id, title FROM events WHERE source='ticketmaster' LIMIT 3\"); [print(r) for r in c.fetchall()]"
```

Pick one music event.

- [ ] **Step 1.2: Fetch the event detail and inspect `_embedded.attractions[]`**

```
python -c "
import httpx, json, os
from app.config import settings
event_id = '<external_id>'  # from Step 1.1
r = httpx.get(f'https://app.ticketmaster.com/discovery/v2/events/{event_id}.json', params={'apikey': settings.ticketmaster_api_key}, timeout=15)
r.raise_for_status()
data = r.json()
atts = data.get('_embedded', {}).get('attractions', [])
print('num attractions:', len(atts))
for a in atts:
    print('- id:', a.get('id'), 'name:', a.get('name'))
    print('  externalLinks keys:', list((a.get('externalLinks') or {}).keys()))
    wiki = (a.get('externalLinks') or {}).get('wiki')
    print('  wiki:', wiki)
"
```

**Decision A:** If any attraction's `externalLinks.wiki[0].url` is populated → embedded is enough, skip the per-attraction call. If `externalLinks` is absent on the embedded attraction, fall through to Step 1.3.

- [ ] **Step 1.3: Fetch a full attraction and confirm `externalLinks.wiki` is there**

```
python -c "
import httpx, json
from app.config import settings
attraction_id = '<attraction id from 1.2>'
r = httpx.get(f'https://app.ticketmaster.com/discovery/v2/attractions/{attraction_id}.json', params={'apikey': settings.ticketmaster_api_key}, timeout=15)
r.raise_for_status()
data = r.json()
print(json.dumps(data.get('externalLinks', {}), indent=2))
import pathlib
pathlib.Path('tests/fixtures/wiki_attraction_sample.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
print('saved fixture')
"
```

Expected: `externalLinks.wiki` is a list with at least one `{'url': 'https://en.wikipedia.org/wiki/…'}`. If the attractions endpoint also lacks wiki links for the artists that had none in `_embedded`, that just means those attractions genuinely have no Wikipedia article on TM's side — the strategy still covers the artists that do.

- [ ] **Step 1.4: Fetch the Wikipedia REST summary and save it**

```
python -c "
import httpx, json, pathlib, urllib.parse
url = '<wiki url from step 1.3>'
from urllib.parse import urlparse, unquote
p = urlparse(url)
host = p.netloc
title = unquote(p.path.rsplit('/', 1)[-1])
api = f'https://{host}/api/rest_v1/page/summary/{title}'
r = httpx.get(api, timeout=15, headers={'User-Agent': 'EventTrackerBot/1.0 (contact@example.com)'})
r.raise_for_status()
data = r.json()
print('keys:', list(data.keys()))
print('extract:', (data.get('extract') or '')[:200])
pathlib.Path('tests/fixtures/wiki_summary_sample.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
"
```

Expected: `extract` field contains a plain-text summary (1–3 paragraphs). Note whether `type` is `standard` (article) or `disambiguation` (skip these).

- [ ] **Step 1.5: Create the fixtures package marker + commit**

Create `backend/tests/fixtures/__init__.py` as an empty file.

```
git add backend/tests/fixtures/__init__.py backend/tests/fixtures/wiki_attraction_sample.json backend/tests/fixtures/wiki_summary_sample.json
git commit -m "test(fixtures): capture TM attraction + Wikipedia REST summary fixtures"
```

- [ ] **Step 1.6: Record decision A**

In your final message on this task, state clearly: "Wiki link is embedded on `_embedded.attractions[i]` in the events endpoint" **or** "Wiki link only present on the separate `/attractions/{id}.json` call — extra API call required." Task 3 branches on this decision.

---

## Task 2 — Pure extractor: `wikipedia.wiki_title_from_url` + `extract_summary`

**Files:**
- Create: `backend/app/ingestion/wikipedia.py`
- Create: `backend/tests/ingestion/test_wikipedia.py`

Two pure functions, no I/O.

- [ ] **Step 2.1: Write the failing tests**

Create `backend/tests/ingestion/test_wikipedia.py`:

```python
import json
from pathlib import Path

from app.ingestion.wikipedia import extract_summary, wiki_title_from_url

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def test_wiki_title_from_url_english():
    assert wiki_title_from_url("https://en.wikipedia.org/wiki/Don_Toliver") == (
        "en.wikipedia.org",
        "Don_Toliver",
    )


def test_wiki_title_from_url_german():
    assert wiki_title_from_url("https://de.wikipedia.org/wiki/Herbert_Gr%C3%B6nemeyer") == (
        "de.wikipedia.org",
        "Herbert_Grönemeyer",
    )


def test_wiki_title_from_url_none_on_non_wiki():
    assert wiki_title_from_url("https://example.com/foo") is None


def test_wiki_title_from_url_none_on_empty():
    assert wiki_title_from_url("") is None
    assert wiki_title_from_url(None) is None  # type: ignore[arg-type]


def test_extract_summary_from_real_fixture():
    body = json.loads((_FIXTURE_DIR / "wiki_summary_sample.json").read_text(encoding="utf-8"))
    summary = extract_summary(body)
    assert summary is not None
    assert len(summary) >= 40


def test_extract_summary_returns_none_for_disambiguation():
    body = {"type": "disambiguation", "extract": "Foo may refer to:"}
    assert extract_summary(body) is None


def test_extract_summary_returns_none_when_extract_missing():
    assert extract_summary({"type": "standard"}) is None


def test_extract_summary_returns_none_on_empty_extract():
    assert extract_summary({"type": "standard", "extract": "   "}) is None
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```
cd backend
python -m pytest tests/ingestion/test_wikipedia.py -v
```

Expected: all 8 tests FAIL (module missing).

- [ ] **Step 2.3: Implement the module**

Create `backend/app/ingestion/wikipedia.py`:

```python
"""Pure helpers for turning a Wikipedia URL into a REST summary lookup.

Two pieces:
- wiki_title_from_url: parse a Wikipedia URL into (host, title).
- extract_summary: pull the plain-text extract from a Wikipedia REST
  /api/rest_v1/page/summary/{title} response, skipping disambiguation pages."""
from urllib.parse import unquote, urlparse


def wiki_title_from_url(url: str | None) -> tuple[str, str] | None:
    """Parse a Wikipedia article URL.

    Returns (host, title) where title is URL-decoded, or None if the URL
    does not look like a Wikipedia article link."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc.endswith("wikipedia.org"):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "wiki":
        return None
    title = unquote("/".join(parts[1:]))
    if not title:
        return None
    return parsed.netloc, title


def extract_summary(body: dict) -> str | None:
    """Return the plain-text summary from a Wikipedia REST summary response.

    Skips disambiguation pages (type == 'disambiguation') — their extract
    is a list of links, not editorial content."""
    if not isinstance(body, dict):
        return None
    if body.get("type") == "disambiguation":
        return None
    extract = body.get("extract")
    if not isinstance(extract, str):
        return None
    text = extract.strip()
    return text or None
```

- [ ] **Step 2.4: Run tests to verify they pass**

```
python -m pytest tests/ingestion/test_wikipedia.py -v
```

Expected: 8 PASS.

- [ ] **Step 2.5: Commit**

```
git add backend/app/ingestion/wikipedia.py backend/tests/ingestion/test_wikipedia.py
git commit -m "feat(wikipedia): pure helpers for URL parsing + summary extraction"
```

---

## Task 3 — Wire Wikipedia lookup into `TicketmasterAdapter`

**Files:**
- Modify: `backend/app/ingestion/ticketmaster.py`
- Modify: `backend/tests/ingestion/test_ticketmaster.py`

Adapter gains a `_fetch_wiki_description(raw)` helper that iterates attractions, follows the first wiki link that returns a real Wikipedia summary, and caches results per artist across the run.

**Assumption (confirm with Task 1 Step 1.6):** If wiki links are on `_embedded.attractions[i].externalLinks.wiki` directly, no extra API call. Otherwise the helper calls `/attractions/{id}.json` (also cached per attraction id).

- [ ] **Step 3.1: Add failing tests**

Read the top of `backend/tests/ingestion/test_ticketmaster.py` to understand existing test constants (`_EVENT_1`, `_SINGLE_PAGE`, `_FakeClient`, `_DETAIL_WITH_INFO`). Then append:

```python
# --- Wikipedia fallback tests -----------------------------------------------

_ATTRACTION_WITH_WIKI = {
    "id": "K8vZ9171oh7",
    "name": "Don Toliver",
    "externalLinks": {
        "wiki": [{"url": "https://en.wikipedia.org/wiki/Don_Toliver"}],
    },
}

_ATTRACTION_NO_WIKI = {
    "id": "K8vZ9171oh8",
    "name": "Local Warmup Act",
    "externalLinks": {},
}

# Version of _EVENT_1 with an attraction embedded (extend the source fixture).
_EVENT_WITH_ATTRACTION = {
    **_EVENT_1,
    "_embedded": {
        **(_EVENT_1.get("_embedded") or {}),
        "attractions": [_ATTRACTION_WITH_WIKI],
    },
}

_WIKI_SUMMARY_RESPONSE = {
    "type": "standard",
    "extract": "Don Toliver is an American rapper and singer from Houston, Texas.",
}


class _FakeWikiClient:
    """Records GET calls; returns a queued JSON body per URL prefix."""

    def __init__(self, url_to_body: dict[str, dict]):
        self._map = url_to_body
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        class _Resp:
            def __init__(self, body):
                self._b = body
            def raise_for_status(self):
                pass
            def json(self):
                return self._b
        for prefix, body in self._map.items():
            if url.startswith(prefix):
                return _Resp(body)
        raise AssertionError(f"unexpected GET {url}")


def test_description_from_wikipedia_when_detail_empty():
    tm = _FakeClient([{"_embedded": {"events": [_EVENT_WITH_ATTRACTION]}, "page": {"number": 0, "totalPages": 1}}])
    wiki = _FakeWikiClient({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver": _WIKI_SUMMARY_RESPONSE,
    })
    adapter = TicketmasterAdapter(client=tm, wiki_client=wiki)
    events = list(adapter.fetch())
    assert events[0].description == (
        "Don Toliver is an American rapper and singer from Houston, Texas."
    )
    assert wiki.calls == [
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver"
    ]


def test_wikipedia_not_called_when_detail_has_description():
    tm = _FakeClient(
        [{"_embedded": {"events": [_EVENT_WITH_ATTRACTION]}, "page": {"number": 0, "totalPages": 1}}],
        detail_map={"tm_001": _DETAIL_WITH_INFO},
    )
    wiki = _FakeWikiClient({})
    adapter = TicketmasterAdapter(client=tm, wiki_client=wiki)
    events = list(adapter.fetch())
    assert events[0].description == "An evening of hard rock classics."
    assert wiki.calls == []


def test_wikipedia_caches_across_events_with_same_attraction():
    """Same artist appears on two events → Wikipedia is hit once."""
    ev1 = {**_EVENT_WITH_ATTRACTION, "id": "tm_001"}
    ev2 = {**_EVENT_WITH_ATTRACTION, "id": "tm_002"}
    tm = _FakeClient([{"_embedded": {"events": [ev1, ev2]}, "page": {"number": 0, "totalPages": 1}}])
    wiki = _FakeWikiClient({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver": _WIKI_SUMMARY_RESPONSE,
    })
    adapter = TicketmasterAdapter(client=tm, wiki_client=wiki)
    events = list(adapter.fetch())
    assert len(events) == 2
    assert all(e.description.startswith("Don Toliver") for e in events)
    assert len(wiki.calls) == 1


def test_description_none_when_attraction_has_no_wiki_link():
    ev = {**_EVENT_1, "_embedded": {**(_EVENT_1.get("_embedded") or {}), "attractions": [_ATTRACTION_NO_WIKI]}}
    tm = _FakeClient([{"_embedded": {"events": [ev]}, "page": {"number": 0, "totalPages": 1}}])
    wiki = _FakeWikiClient({})
    adapter = TicketmasterAdapter(client=tm, wiki_client=wiki)
    events = list(adapter.fetch())
    assert events[0].description is None
    assert wiki.calls == []


def test_description_none_when_wiki_summary_is_disambiguation():
    tm = _FakeClient([{"_embedded": {"events": [_EVENT_WITH_ATTRACTION]}, "page": {"number": 0, "totalPages": 1}}])
    wiki = _FakeWikiClient({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver":
            {"type": "disambiguation", "extract": "Don may refer to..."},
    })
    adapter = TicketmasterAdapter(client=tm, wiki_client=wiki)
    events = list(adapter.fetch())
    assert events[0].description is None


def test_no_wiki_client_means_no_lookup():
    """Default behavior — adapter constructed without wiki_client does not error."""
    tm = _FakeClient([{"_embedded": {"events": [_EVENT_WITH_ATTRACTION]}, "page": {"number": 0, "totalPages": 1}}])
    adapter = TicketmasterAdapter(client=tm)
    events = list(adapter.fetch())
    assert events[0].description is None
```

Update `_FakeClient` in the test file if it doesn't already support `detail_map`. It likely does (from earlier work).

- [ ] **Step 3.2: Run new tests to confirm they fail**

```
cd backend
python -m pytest tests/ingestion/test_ticketmaster.py -k "wiki" -v
```

Expected: FAIL — `TicketmasterAdapter.__init__` does not accept `wiki_client`.

- [ ] **Step 3.3: Implement adapter changes**

In `backend/app/ingestion/ticketmaster.py`, add imports at the top:

```python
from app.ingestion.wikipedia import extract_summary, wiki_title_from_url
```

Add a module-level constant:

```python
_WIKI_USER_AGENT = "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"
```

Change `TicketmasterAdapter.__init__`:

```python
    def __init__(
        self,
        client: httpx.Client | None = None,
        wiki_client: httpx.Client | None = None,
    ):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key
        self._wiki_client = wiki_client
        # Per-run cache: wiki URL → description text or None (negative caching too).
        self._wiki_cache: dict[str, str | None] = {}
```

Add a new method after `_fetch_detail`:

```python
    def _fetch_wiki_description_for_event(self, raw: dict) -> str | None:
        """Iterate the event's embedded attractions; return the first
        Wikipedia summary text found via externalLinks.wiki."""
        if self._wiki_client is None:
            return None
        for att in (raw.get("_embedded") or {}).get("attractions") or []:
            wiki_links = ((att.get("externalLinks") or {}).get("wiki")) or []
            for link in wiki_links:
                url = link.get("url") if isinstance(link, dict) else None
                desc = self._lookup_wiki_summary(url)
                if desc:
                    return desc
        return None

    def _lookup_wiki_summary(self, url: str | None) -> str | None:
        if not url:
            return None
        if url in self._wiki_cache:
            return self._wiki_cache[url]
        parsed = wiki_title_from_url(url)
        if parsed is None:
            self._wiki_cache[url] = None
            return None
        host, title = parsed
        api = f"https://{host}/api/rest_v1/page/summary/{title}"
        try:
            resp = self._wiki_client.get(api, headers={"User-Agent": _WIKI_USER_AGENT})
            resp.raise_for_status()
            body = resp.json()
        except Exception:
            logger.warning("Wikipedia summary fetch failed for %s", api)
            self._wiki_cache[url] = None
            return None
        text = extract_summary(body)
        self._wiki_cache[url] = text
        return text
```

Replace the description block in `_parse` (currently lines 113-117):

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
                description = self._fetch_wiki_description_for_event(raw)
```

- [ ] **Step 3.4: Run all TM adapter tests**

```
python -m pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all previously-passing tests still pass; 6 new tests pass. If Task 1 Step 1.6 revealed the wiki link is NOT on the embedded attraction but only on the full attraction detail, adjust `_fetch_wiki_description_for_event` to first call `_fetch_attraction_detail(att['id'])` — add that helper analogous to `_fetch_detail` — and update tests accordingly.

- [ ] **Step 3.5: Commit**

```
git add backend/app/ingestion/ticketmaster.py backend/tests/ingestion/test_ticketmaster.py
git commit -m "feat(ticketmaster): Wikipedia-summary fallback via attraction wiki links"
```

---

## Task 4 — Add `hide_events_without_description` config toggle

**Files:**
- Modify: `backend/app/config.py`
- (No dedicated tests here — behavior is covered by `test_visible_events_filter.py` in Task 5)

- [ ] **Step 4.1: Add the setting**

In `backend/app/config.py`, add after `default_user_id: str = "local"`:

```python
    # Filter empty-description events from user-facing queries.
    # When True (default), list endpoints, agent tools, and the embedding
    # feed skip events whose description is null or empty. Flip via
    # HIDE_EVENTS_WITHOUT_DESCRIPTION=false to include them (useful during
    # backfill validation).
    hide_events_without_description: bool = True
```

- [ ] **Step 4.2: Commit**

```
git add backend/app/config.py
git commit -m "feat(config): add HIDE_EVENTS_WITHOUT_DESCRIPTION toggle (default on)"
```

---

## Task 5 — Add `visible_events_filter()` helper (respects toggle)

**Files:**
- Modify: `backend/app/db/models/event.py`
- Create: `backend/tests/db/test_visible_events_filter.py`

Helper reads `settings.hide_events_without_description` at call time. Returns strict filter when on, loose (`is_active` only) when off.

- [ ] **Step 5.1: Write the failing tests**

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


def test_filter_returns_only_active_with_description_when_toggle_on(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", True)

    _make(db_session, id="ok",       description="Real text.",  is_active=True)
    _make(db_session, id="empty",    description="",            is_active=True, external_id="e2")
    _make(db_session, id="null",     description=None,          is_active=True, external_id="e3")
    _make(db_session, id="inactive", description="Real text.",  is_active=False, external_id="e4")

    ids = {r.id for r in db_session.query(Event).filter(visible_events_filter()).all()}
    assert ids == {"ok"}


def test_filter_ignores_description_when_toggle_off(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", False)

    _make(db_session, id="ok",       description="Real text.",  is_active=True)
    _make(db_session, id="empty",    description="",            is_active=True, external_id="e2")
    _make(db_session, id="null",     description=None,          is_active=True, external_id="e3")
    _make(db_session, id="inactive", description="Real text.",  is_active=False, external_id="e4")

    ids = {r.id for r in db_session.query(Event).filter(visible_events_filter()).all()}
    assert ids == {"ok", "empty", "null"}  # active without desc are visible; inactive still hidden


def test_filter_composes_with_other_filters(db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", True)

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

- [ ] **Step 5.2: Run tests to confirm they fail**

```
python -m pytest tests/db/test_visible_events_filter.py -v
```

Expected: FAIL — `visible_events_filter` missing.

- [ ] **Step 5.3: Implement**

Modify `backend/app/db/models/event.py`. Change the sqlalchemy import at the top from:

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

    Always requires `is_active`. When `settings.hide_events_without_description`
    is True (default), also requires a non-empty description. Reading the
    setting at call time lets the operator flip the toggle without touching
    call sites."""
    from app.config import settings

    if not settings.hide_events_without_description:
        return Event.is_active == True  # noqa: E712
    return and_(
        Event.is_active == True,  # noqa: E712
        Event.description.isnot(None),
        Event.description != "",
    )
```

- [ ] **Step 5.4: Run tests**

```
python -m pytest tests/db/test_visible_events_filter.py -v
```

Expected: 3 PASS.

- [ ] **Step 5.5: Commit**

```
git add backend/app/db/models/event.py backend/tests/db/test_visible_events_filter.py
git commit -m "feat(events): visible_events_filter helper (respects hide toggle)"
```

---

## Task 6 — Apply filter to the list endpoint (`routes_events.py`)

**Files:**
- Modify: `backend/app/api/routes_events.py`
- Modify: `backend/tests/api/test_routes_events.py`

- [ ] **Step 6.0: Fix pre-existing fixtures**

In `backend/tests/api/test_routes_events.py`, the `setup` fixture creates events without a `description`. Add `description=f"Description for event {i}."` to the `Event(...)` call inside the loop so the existing list-endpoint tests still see all three events after the filter is enabled.

Run:

```
python -m pytest tests/api/test_routes_events.py -v
```

Expected: still all pass.

- [ ] **Step 6.1: Add failing tests**

Append to `backend/tests/api/test_routes_events.py`:

```python
def test_list_events_hides_events_without_description(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event
    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="With desc",
              description="Real text.", start_datetime=now, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="No desc",
              description=None, start_datetime=now, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
        Event(id="empty_desc", external_id="c", source="ticketmaster", title="Empty desc",
              description="", start_datetime=now, category="music",
              tags=[], source_url="https://x/c", raw_data={}),
    ])
    db_session.commit()

    resp = client.get("/events?date_from=2026-07-15&date_to=2026-07-16")
    assert resp.status_code == 200
    data = resp.json()
    ids = {e["id"] for e in data["events"]}
    assert ids == {"with_desc"}


def test_list_events_shows_no_desc_when_toggle_off(client, db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", False)

    from datetime import datetime, timezone
    from app.db.models import Event
    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="With desc",
              description="Real text.", start_datetime=now, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="No desc",
              description=None, start_datetime=now, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
    ])
    db_session.commit()

    resp = client.get("/events?date_from=2026-07-15&date_to=2026-07-16")
    ids = {e["id"] for e in resp.json()["events"]}
    assert ids == {"with_desc", "no_desc"}


def test_get_event_returns_event_even_without_description(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event
    db_session.add(Event(id="no_desc_direct", external_id="d", source="ticketmaster",
                         title="Direct fetch", description=None,
                         start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
                         category="music", tags=[], source_url="https://x/d", raw_data={}))
    db_session.commit()

    resp = client.get("/events/no_desc_direct")
    assert resp.status_code == 200
    assert resp.json()["id"] == "no_desc_direct"
```

- [ ] **Step 6.2: Run tests to confirm the first two fail**

```
python -m pytest tests/api/test_routes_events.py::test_list_events_hides_events_without_description tests/api/test_routes_events.py::test_list_events_shows_no_desc_when_toggle_off -v
```

- [ ] **Step 6.3: Change the list endpoint filter**

In `backend/app/api/routes_events.py`, add:

```python
from app.db.models.event import visible_events_filter
```

Replace the line that filters `Event.is_active == True` in `list_events` with:

```python
    qry = db.query(Event).filter(visible_events_filter())
```

- [ ] **Step 6.4: Run tests**

```
python -m pytest tests/api/test_routes_events.py -v
```

Expected: all pass.

- [ ] **Step 6.5: Commit**

```
git add backend/app/api/routes_events.py backend/tests/api/test_routes_events.py
git commit -m "feat(events): list endpoint hides no-desc events via visible_events_filter"
```

---

## Task 7 — Apply filter to agent tools (`search_events`, `get_recommendations`)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/tests/agent/test_tools.py`

- [ ] **Step 7.0: Fix pre-existing fixtures**

Three tests in `backend/tests/agent/test_tools.py` seed Events with `description=""` and expect them in `search_events` results:

- `test_search_events_defaults_to_today_plus_3d`
- `test_search_events_explicit_bounds_override_default`
- `test_search_events_one_bound_does_not_trigger_default`

Change `description=""` → `description="Real."` in each.

Run:
```
python -m pytest tests/agent/test_tools.py -v
```
Expected: still pass.

- [ ] **Step 7.1: Add failing test**

Append to `test_tools.py`:

```python
def test_search_events_hides_no_description(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.agent import tools

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="visible", external_id="a", source="ticketmaster", title="Yes",
              description="Real.", start_datetime=now, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="hidden", external_id="b", source="ticketmaster", title="No",
              description=None, start_datetime=now, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
    ])
    db_session.commit()

    rows = tools.search_events.invoke({"date_from": "2026-07-15", "date_to": "2026-07-16"})
    ids = {r["id"] for r in rows}
    assert ids == {"visible"}
```

- [ ] **Step 7.2: Change `search_events` and `get_recommendations`**

In `backend/app/agent/tools.py`, add:

```python
from app.db.models.event import visible_events_filter
```

In `search_events` change:
```python
        q = session.query(Event).filter(Event.is_active == True)  # noqa: E712
```
to:
```python
        q = session.query(Event).filter(visible_events_filter())
```

In `get_recommendations` (id hydration), change:
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

Do NOT change `get_calendar` (saved events stay visible) or existence checks in save/unsave.

- [ ] **Step 7.3: Run tests + commit**

```
python -m pytest tests/agent/test_tools.py -v
git add backend/app/agent/tools.py backend/tests/agent/test_tools.py
git commit -m "feat(agent): hide no-desc events from search + recommend"
```

---

## Task 8 — Apply visible filter to embedding feed

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

Two changes to `embed_new_events`: (a) keep-set uses `visible_events_filter()`, (b) rows to embed use `visible_events_filter()`.

- [ ] **Step 8.1: Inspect existing scheduler tests**

```
python -m pytest tests/ingestion/test_scheduler.py -v --collect-only
```

Note the existing chroma-mocking pattern (likely `monkeypatch.setattr(scheduler, "chroma_upsert_events", …)`, `scheduler.chroma_store.all_ids`, `scheduler.chroma_store.delete_by_ids`).

- [ ] **Step 8.2: Add failing tests**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
def test_embed_new_events_skips_events_without_description(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.ingestion import scheduler

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="A",
              description="Real.", start_datetime=now, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="B",
              description=None, start_datetime=now, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
    ])
    db_session.commit()

    upserted: list = []
    monkeypatch.setattr(scheduler, "chroma_upsert_events", lambda payload: upserted.extend(p.id for p in payload))
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", lambda: set())
    monkeypatch.setattr(scheduler.chroma_store, "delete_by_ids", lambda ids: None)

    scheduler.embed_new_events(db_session)
    assert upserted == ["with_desc"]


def test_embed_new_events_purges_no_description_from_chroma(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.db.models import Event
    from app.ingestion import scheduler

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add(Event(id="no_desc", external_id="b", source="ticketmaster", title="B",
                         description=None, start_datetime=now, category="music",
                         tags=[], source_url="https://x/b", raw_data={}))
    db_session.commit()

    deleted: list = []
    monkeypatch.setattr(scheduler, "chroma_upsert_events", lambda payload: None)
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", lambda: {"no_desc", "gone"})
    monkeypatch.setattr(scheduler.chroma_store, "delete_by_ids", lambda ids: deleted.extend(ids))

    scheduler.embed_new_events(db_session)
    assert set(deleted) == {"no_desc", "gone"}
```

- [ ] **Step 8.3: Implement**

In `backend/app/ingestion/scheduler.py`, add:

```python
from app.db.models.event import visible_events_filter
```

Replace `embed_new_events`. Change:
```python
    all_event_ids = {row[0] for row in session.query(Event.id).all()}
    stale = list(chroma_store.all_ids() - all_event_ids)
```
to:
```python
    visible_ids = {row[0] for row in session.query(Event.id).filter(visible_events_filter()).all()}
    stale = list(chroma_store.all_ids() - visible_ids)
```

And change:
```python
    rows = session.query(Event).filter(Event.is_active == True).all()  # noqa: E712
```
to:
```python
    rows = session.query(Event).filter(visible_events_filter()).all()
```

- [ ] **Step 8.4: Run tests + commit**

```
python -m pytest tests/ingestion/test_scheduler.py -v
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): visible-only embeddings (respects hide toggle)"
```

---

## Task 9 — Backfill script for existing DB rows

**Files:**
- Create: `backend/scripts/backfill_tm_descriptions.py`
- Create: `backend/tests/scripts/test_backfill_tm_descriptions.py`

Walks TM events with missing descriptions. For each, if the event has a stored `_embedded.attractions` in `raw_data`, iterate its wiki links and try Wikipedia. Otherwise call the TM attractions endpoint. Same extractor as ingestion.

- [ ] **Step 9.1: Write the failing tests**

Create `backend/tests/scripts/test_backfill_tm_descriptions.py`:

```python
from datetime import datetime, timezone

from app.db.models import Event
from scripts import backfill_tm_descriptions


class _FakeHttp:
    def __init__(self, url_to_body: dict[str, dict]):
        self._map = url_to_body
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        class _R:
            def __init__(self, b): self._b = b
            def raise_for_status(self): pass
            def json(self): return self._b
        for prefix, b in self._map.items():
            if url.startswith(prefix): return _R(b)
        raise AssertionError(f"unexpected GET {url}")


_ATTR_WITH_WIKI = {
    "externalLinks": {"wiki": [{"url": "https://en.wikipedia.org/wiki/Don_Toliver"}]}
}


def _seed(session, id_, description, source="ticketmaster", raw_data=None):
    session.add(Event(
        id=id_, external_id=id_, source=source, title="T", description=description,
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music", tags=[], source_url="https://tm/e", raw_data=raw_data or {},
    ))
    session.commit()


def test_backfill_updates_missing_descriptions(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e2", "",   raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e3", "Already.", raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e4", None, source="eventbrite", raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})

    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver":
            {"type": "standard", "extract": "Don Toliver is an American rapper."},
    })
    report = backfill_tm_descriptions.run(db_session, http_client=http)

    assert report["scanned"] == 2
    assert report["updated"] == 2
    assert report["failed"] == 0
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description.startswith("Don Toliver")
    assert db_session.query(Event).filter_by(id="e2").one().description.startswith("Don Toliver")
    assert db_session.query(Event).filter_by(id="e3").one().description == "Already."
    assert db_session.query(Event).filter_by(id="e4").one().description is None


def test_backfill_is_idempotent(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver":
            {"type": "standard", "extract": "Don Toliver is an American rapper."},
    })
    first = backfill_tm_descriptions.run(db_session, http_client=http)
    second = backfill_tm_descriptions.run(db_session, http_client=http)
    assert first["updated"] == 1
    assert second["scanned"] == 0


def test_backfill_records_failure_when_no_wiki_link(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [{"externalLinks": {}}]}})
    http = _FakeHttp({})
    report = backfill_tm_descriptions.run(db_session, http_client=http)
    assert report["scanned"] == 1
    assert report["updated"] == 0
    assert report["failed"] == 1
```

- [ ] **Step 9.2: Implement script**

Create `backend/scripts/backfill_tm_descriptions.py`:

```python
"""Backfill missing description for existing Ticketmaster events via Wikipedia.

For each event where source='ticketmaster' AND description is null/empty,
look at raw_data._embedded.attractions[].externalLinks.wiki[].url, follow
the first that yields a Wikipedia REST summary. Commit per row for partial
progress. Idempotent."""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.session import SessionLocal
from app.ingestion.wikipedia import extract_summary, wiki_title_from_url

logger = logging.getLogger(__name__)

_WIKI_USER_AGENT = "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"


def _wiki_urls_for(event: Event) -> list[str]:
    atts = (event.raw_data or {}).get("_embedded", {}).get("attractions") or []
    urls: list[str] = []
    for att in atts:
        for link in ((att.get("externalLinks") or {}).get("wiki")) or []:
            if isinstance(link, dict) and link.get("url"):
                urls.append(link["url"])
    return urls


def _lookup(http_client, url: str, cache: dict[str, str | None]) -> str | None:
    if url in cache:
        return cache[url]
    parsed = wiki_title_from_url(url)
    if parsed is None:
        cache[url] = None
        return None
    host, title = parsed
    api = f"https://{host}/api/rest_v1/page/summary/{title}"
    try:
        r = http_client.get(api, headers={"User-Agent": _WIKI_USER_AGENT})
        r.raise_for_status()
        body = r.json()
    except Exception:
        logger.warning("wiki summary fetch failed for %s", api)
        cache[url] = None
        return None
    text = extract_summary(body)
    cache[url] = text
    return text


def _missing(session: Session) -> list[Event]:
    return (
        session.query(Event)
        .filter(Event.source == "ticketmaster")
        .filter(or_(Event.description.is_(None), Event.description == ""))
        .all()
    )


def run(session: Session, http_client) -> dict:
    rows = _missing(session)
    scanned = len(rows)
    updated = 0
    failed = 0
    cache: dict[str, str | None] = {}

    logger.info("backfill: %d TM events missing description", scanned)
    for i, row in enumerate(rows, start=1):
        desc = None
        for url in _wiki_urls_for(row):
            desc = _lookup(http_client, url, cache)
            if desc:
                break
        if desc:
            row.description = desc
            session.commit()
            updated += 1
        else:
            failed += 1
        if i % 25 == 0:
            logger.info("progress %d/%d (updated=%d)", i, scanned, updated)

    logger.info("backfill complete — scanned=%d updated=%d failed=%d", scanned, updated, failed)
    return {"scanned": scanned, "updated": updated, "failed": failed}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        with httpx.Client(timeout=15) as http:
            report = run(session, http)
    finally:
        session.close()
    print(f"scanned={report['scanned']} updated={report['updated']} failed={report['failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9.3: Run tests + commit**

```
python -m pytest tests/scripts/test_backfill_tm_descriptions.py -v
git add backend/scripts/backfill_tm_descriptions.py backend/tests/scripts/test_backfill_tm_descriptions.py
git commit -m "feat(scripts): backfill TM descriptions from Wikipedia summaries"
```

---

## Task 10 — Wire the adapter to pass an httpx client for Wikipedia in prod

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`

Currently `run_ingestion` constructs `TicketmasterAdapter()` with no wiki client, so the fallback stays dormant in production. Fix that.

- [ ] **Step 10.1: Change default-adapter construction**

In `backend/app/ingestion/scheduler.py`, find `_default_adapters()` and change it so `TicketmasterAdapter` is constructed with a real httpx client passed as `wiki_client`:

```python
def _default_adapters() -> list[SourceAdapter]:
    wiki_client = httpx.Client(timeout=15)
    return [TicketmasterAdapter(wiki_client=wiki_client), HamburgScraper()]
```

Add `import httpx` at the top if not already imported.

Note: this leaks the client if not closed. For the nightly job the process ends shortly after, but if there's a cleaner shutdown hook in `run_ingestion`, close it there. Otherwise a `try/finally` around the ingestion loop closing `wiki_client` is appropriate — check `run_ingestion` structure and add if needed.

- [ ] **Step 10.2: Commit**

```
git add backend/app/ingestion/scheduler.py
git commit -m "feat(scheduler): pass wiki_client to TicketmasterAdapter in production ingest"
```

---

## Task 11 — Full suite verification

- [ ] **Step 11.1: Run every backend test**

```
cd backend
python -m pytest -v
```

Expected: all pass. Diagnose any regression from fixtures that seeded events without description.

---

## Task 12 — Manual live backfill (operator step)

- [ ] **Step 12.1: Snapshot DB**

```
cp backend/event_tracker.db backend/event_tracker.db.bak-2026-07-03
```

- [ ] **Step 12.2: Coverage before**

```
python -c "
import sqlite3
c = sqlite3.connect('backend/event_tracker.db').cursor()
c.execute(\"SELECT source, COUNT(*), SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) FROM events GROUP BY source\")
for row in c.fetchall(): print(row)
"
```

- [ ] **Step 12.3: Run the backfill**

```
cd backend
python -m scripts.backfill_tm_descriptions
```

Expected runtime: ~5–15 min for 318 events (Wikipedia REST is fast; artist cache dedupes).

- [ ] **Step 12.4: Coverage after + re-embed**

Same command as 12.2, then:

```
python -c "
from app.db.session import SessionLocal
from app.ingestion.scheduler import embed_new_events
s = SessionLocal(); embed_new_events(s); s.close()
"
```

---

## Notes for the executor

- Every commit contains a passing test suite for the code touched in that task. Do not batch.
- **`_FakeClient` in `test_ticketmaster.py`** may need extension to accept `detail_map`. Check its current shape before Task 3 tests are added and adapt if needed.
- **If Task 1 recon shows no attraction has a wiki link across 3 sampled events**, escalate before Task 2 — the strategy relies on the link existing for a nontrivial fraction of events. Sample more events (10+) before giving up; if truly zero coverage, the fallback is Part C alone (hide-only).
- **The `hide_events_without_description` toggle also disables description-filtering in the embedding feed and stale sweep.** This is intentional — when the operator flips it off, empty-desc events should re-appear in Chroma too.
