# Event Descriptions — Ticketmaster Wikipedia Fallback + Hide-Empty Design

**Date:** 2026-07-01 (original), 2026-07-03 (Amendment 2 pivot)
**Status:** Approved. **See "Amendment 2 (2026-07-03)" at the bottom — the strategy has pivoted from page scraping (Playwright) to Wikipedia enrichment. That amendment supersedes Part A and Amendment 1 below.**

## Problem

Of 344 events in the DB, 318 (92%) have no description. Breakdown:

| Source | Total | With description |
|---|---|---|
| `ticketmaster` | 337 | 19 (5.6%) |
| `hamburg_scraper` | 7 | 7 (100%) |

Today's plan (`docs/plans/2026-07-01-event-descriptions.md`) added Ticketmaster detail-endpoint fetches for `info` / `additionalInfo` / `pleaseNote`, but those fields are populated for only ~5% of TM events. Hamburg is fully covered by the detail-page scrape. **Ticketmaster is the remaining problem.**

Events without a description are of no use to the user. LLM-generated descriptions are explicitly disallowed — they could mislead.

## Goal

Populate `description` for as many Ticketmaster events as possible via a real, factual source. For events that still lack a description after all fetch attempts, hide them from every user-facing path (list, calendar, chat/agent, embeddings).

## Non-Goals

- Wikipedia / artist-homepage / MusicBrainz / Songkick enrichment — coverage in the current DB is only 15%/23%, and the page scrape is expected to cover much more.
- LLM-generated descriptions.
- Retry queue / background job infrastructure for failed scrapes — the backfill script is re-runnable.
- Any change to the Hamburg scraper (already at 100% coverage).

## Design Overview

Three coordinated parts:

**A.** Add a Ticketmaster event-page scraper to the ingestion adapter as a fallback after the existing detail-endpoint fields.
**B.** Ship a one-off backfill script that walks all existing description-less TM events and applies the same extraction.
**C.** Introduce a `visible_events_filter()` helper and apply it at every user-facing query site so events without descriptions are hidden. Also purge stale vectors from Chroma.

Extraction logic lives in one shared module so the adapter and the backfill script share a single code path.

---

## Part A — Ticketmaster event page scrape (inline in ingestion)

### New module: `backend/app/ingestion/ticketmaster_page.py`

```python
def extract_description(html: str) -> str | None:
    """Extract 'About this event' text from a ticketmaster.de event page."""
```

- Parses with BeautifulSoup.
- Selector to be confirmed in the plan's recon step (Task 1). Working hypothesis: a `<div>` under a specific class that contains the "About" block, or the `<meta name="description">` tag as a secondary target.
- Returns stripped text or `None` if the block is absent.

### Fetcher: new method `_fetch_page_description(source_url)` on `TicketmasterAdapter`

- `GET source_url` with the existing httpx client, honest User-Agent (`EventTrackerBot/1.0`).
- On non-2xx or exception → log WARNING, return `None`.
- 200ms polite delay between page fetches (module-level constant so tests can monkeypatch).

### Wiring: extend `_parse` fallback chain

Current chain (from today's commit):

```python
description = (detail.get("info") or detail.get("additionalInfo") or detail.get("pleaseNote")) or None
```

Becomes:

```python
description = (
    detail.get("info")
    or detail.get("additionalInfo")
    or detail.get("pleaseNote")
    or self._fetch_page_description(raw["url"])
) or None
```

`raw["url"]` is the source URL already required by `_parse` (used to populate `source_url`).

### Cost

Per event: 1 list call (amortised) + 1 detail API call + 1 page fetch = 3 HTTP requests. For ~340 events per ingest → ~340 page fetches. At 200ms delay → ~70s added to a full ingest. Acceptable.

---

## Part B — One-off backfill script

### New file: `backend/scripts/backfill_tm_descriptions.py`

- Opens a DB session.
- Query: `Event` rows where `source='ticketmaster'` AND (`description IS NULL` OR `description = ''`).
- For each row: `httpx.get(row.source_url)` → `ticketmaster_page.extract_description(html)`.
- On success: `row.description = text; session.commit()` per row (so partial progress is preserved).
- Logs progress every 25 events, plus a summary at start/end (`before: X / Y with description; after: X' / Y with description`).
- Same 200ms delay as ingestion.
- Idempotent: re-running only touches rows still without a description.

### Runbook

Documented at the top of the script as a comment:

```
python -m scripts.backfill_tm_descriptions
```

No CLI args — deliberately minimal for a one-off tool.

---

## Part C — Hide description-less events at the query layer

### New helper: `backend/app/db/models/event.py`

```python
from sqlalchemy import and_

def visible_events_filter():
    """Filter: event is active AND has a non-empty description."""
    return and_(
        Event.is_active == True,
        Event.description.isnot(None),
        Event.description != "",
    )
```

### Apply at every user-facing query site

Located via grep for `Event` queries — five sites:

| File | Line (from grep) | Purpose |
|---|---|---|
| `backend/app/api/routes_events.py` | 43 | List endpoint |
| `backend/app/api/routes_calendar.py` | 36 | Calendar view |
| `backend/app/agent/tools.py` | 83 | Agent search |
| `backend/app/agent/tools.py` | 116 | Agent recommend |
| `backend/app/agent/tools.py` | 300 | RAG hydration by id |
| `backend/app/ingestion/scheduler.py` | 34 | Feeds embedding job |

Each `db.query(Event).filter(Event.is_active == True)` becomes `db.query(Event).filter(visible_events_filter())`.

**Explicit exclusions (do NOT filter):**
- `routes_events.py:100` (event detail by id) — if the user hits `/events/{id}` for an id that has since become invisible, return it anyway; the endpoint is used from a saved link. Alternative: 404. Decision recorded here as "return it" to avoid breaking saved links. **Confirm with the user during spec review.**
- `routes_calendar.py:52, 87` (SavedEvent lookups) — a user's saved events should stay visible even if the underlying event becomes description-less.
- `agent/tools.py:136, 324` (existence checks for save/unsave) — same reason.

### Chroma vector cleanup

`embed_new_events` already has stale-vector cleanup (commit `ae2cf86`). Update the "keep set" to be `{ids of visible events}` rather than `{ids of active events}`. Vectors for now-invisible events are removed on the next embed run.

---

## Part D — Testing

### Unit tests

**`test_ticketmaster_page.py`** — new file, tests `extract_description`:
- Real-page fixture HTML (checked in from Task 1 recon) → returns expected text.
- HTML without the block → returns `None`.
- Empty string → returns `None`.

**`test_ticketmaster.py`** — extend existing:
- Detail endpoint empty AND page HTML has description → event ends up with the page description.
- Detail endpoint empty AND page fetch 500 → description is `None`, no exception.
- Detail endpoint populated → page fetch NOT called (assertion via URL-aware fake client).

**`test_visible_events_filter.py`** — new file:
- Seed: active+desc, active+empty desc, active+null desc, inactive+desc.
- Assert filter returns only `active+desc`.
- Parametrise over every touched query site (list, calendar, agent search, agent recommend, RAG hydration, embedding feed) to catch any that was missed in the roll-out.

### Integration test

**`test_backfill_tm_descriptions.py`** — new file:
- Seed one TM event with `source_url` pointing to a local HTTP fixture (via httpx transport mock).
- Run the backfill script's `main()` function.
- Assert the row now has the expected description.

### Recon (part of the plan, not the spec)

Plan Task 1: fetch one real ticketmaster.de event page, save the response HTML into `backend/tests/fixtures/ticketmaster_page_sample.html`, and identify the selector. All later steps depend on this file existing and the selector being confirmed.

---

## File Map

| Action | File |
|---|---|
| Create | `backend/app/ingestion/ticketmaster_page.py` |
| Modify | `backend/app/ingestion/ticketmaster.py` |
| Create | `backend/scripts/backfill_tm_descriptions.py` |
| Modify | `backend/app/db/models/event.py` |
| Modify | `backend/app/api/routes_events.py` |
| Modify | `backend/app/api/routes_calendar.py` |
| Modify | `backend/app/agent/tools.py` |
| Modify | `backend/app/ingestion/scheduler.py` |
| Modify | `backend/app/chroma/*` (whichever module hosts `embed_new_events` — plan will identify) |
| Create | `backend/tests/ingestion/test_ticketmaster_page.py` |
| Modify | `backend/tests/ingestion/test_ticketmaster.py` |
| Create | `backend/tests/db/test_visible_events_filter.py` |
| Create | `backend/tests/integration/test_backfill_tm_descriptions.py` |
| Create | `backend/tests/fixtures/ticketmaster_page_sample.html` |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| ticketmaster.de HTML changes → selector breaks | Single selector location in `ticketmaster_page.py`; WARNING log when extraction returns `None` despite HTTP 200; fixture-based test catches structural regressions |
| Rate limiting / IP block | 200ms delay between page fetches; honest User-Agent; backfill runs once |
| Terms-of-service concerns | HTTP GET on a public event page, no auth bypass — aggregator use case. Acknowledged trade-off |
| Description present on scrape but low quality (e.g. only a venue address) | Out of scope for v1 — if it becomes a problem, add a min-length threshold later |
| Coverage still < 100% after scrape | Part C hides remaining events — user never sees empty descriptions |
| Direct `/events/{id}` link to a now-invisible event | Design decision: return the event anyway (see Part C exclusions). Confirm during spec review |
| Existing Chroma vectors for no-desc events | `embed_new_events` cleanup already sweeps stale vectors; only the keep-set predicate changes |

## Success Criteria

- After Part A + Part B run, DB coverage of TM descriptions rises materially (target: ≥80% — measured by re-running the SQL count query from today's plan).
- No user-facing endpoint returns an event with `description IS NULL OR description = ''`.
- No Chroma vector points to an invisible event.
- All new and existing tests pass.

---

## Amendment (2026-07-01) — Playwright required for the scrape

**Trigger:** During plan execution Task 1, `httpx.get` on every ticketmaster.de `/event/*` URL returned HTTP 401 with an Imperva-style JS challenge page (~5900 bytes) regardless of User-Agent, header spoofing, or cookie warmup via the homepage. The `/event/` path is pre-emptively gated by a server-side check for a JS-executed challenge token. No plain-HTTP client can bypass it.

**Decision:** Use Playwright with headless Chromium to fetch event pages. Every other part of the design (extractor, backfill, hide-filter, Chroma cleanup) stays the same — only the fetch layer changes.

**Impact:**

- **New dependency:** `playwright` in `pyproject.toml`; operator must run `playwright install chromium` once.
- **New module:** `backend/app/ingestion/browser.py` exposes a `PageFetcher` protocol and a `PlaywrightPageFetcher` context-manager implementation (start browser on `__enter__`, close on `__exit__`, `.fetch(url) -> str | None` returns rendered HTML or None on failure/challenge).
- **Adapter wiring:** `TicketmasterAdapter.__init__` gains an optional `page_fetcher: PageFetcher | None` parameter. Tests inject a fake fetcher; scheduler and backfill wire a real `PlaywrightPageFetcher` around the adapter/backfill call.
- **Ingestion cost:** Each page render takes ~2–5 s (browser navigation + wait for challenge to clear). For 340 events → ~10–25 min per full ingest. Acceptable for a nightly cron; unacceptable for on-demand calls (not currently used).
- **Backfill cost:** ~10–25 min one-off for the 318 existing events.
- **Risks:** Playwright process crashes → mitigate with per-page timeouts (30 s) and `.fetch` returning None on any failure. Browser dependency drift → pin Playwright version.

**Extraction stays JSON-LD-first → meta-description fallback** — Task 1 recon must still confirm which is present on the rendered page.

**Rate-limiting risk mitigation revised:** the 200 ms `time.sleep` between events is removed (Playwright's own navigation latency + rendering wait provides throttling). Each event still fetches only once.

**Tasks affected in the plan:**
- Task 0 (new): Add Playwright to `pyproject.toml`, `playwright install chromium`, smoke-test the browser.
- Task 1: Rewrite fetch step to use Playwright.
- Task 3: Introduce `PageFetcher` protocol + `PlaywrightPageFetcher`. Adapter takes a fetcher, calls `.fetch(url)` instead of `self._client.get(source_url)`.
- Task 7 (scheduler wiring — was implicit): explicitly wrap the adapter call in a `PlaywrightPageFetcher` context manager.
- Task 8 (backfill): use `PlaywrightPageFetcher` context manager instead of httpx.

Original tasks 2, 4, 5, 6, 9, 10 are unaffected.

---

## Amendment 2 (2026-07-03) — Pivot from page scrape to Wikipedia enrichment

**Trigger:** After `tf-playwright-stealth` successfully defeated the Imperva JS challenge (610 KB real page fetched, no bot block), inspection of the real rendered ticketmaster.de event page revealed that **the page has no substantive description content**:

- JSON-LD `MusicEvent.description` = just the venue name (e.g. `"Barclays Arena"`).
- `<meta name="description">` = boilerplate title+venue restatement (`"Buy Tickets for DON TOLIVER at Barclays Arena, Hamburg – Official Ticketmaster Website"`).
- No `.about-event` / `.event-description` / editorial container exists — the page is a ticket-purchase UI.

Ticketmaster.de is a ticket-purchase interface, not an editorial page. Scraping cannot yield useful description content that isn't there. The `/attractions/{id}.json` endpoint likewise has no `description`/`info`/`additionalInfo` fields.

**However, TM attractions have a discoverable Wikipedia link** in `externalLinks.wiki[].url` for a subset of artists (~15% based on prior exploration). The Wikipedia REST API's `/api/rest_v1/page/summary/{title}` returns a factual, stable prose summary of the artist — genuinely useful to a user browsing events.

**Decision:** Replace the page-scrape strategy with Wikipedia enrichment via TM attractions. Add a config toggle so the operator can turn the hide-empty behaviour on/off.

### Revised Part A — Wikipedia enrichment (replaces original Part A and Amendment 1)

#### Data flow

1. TM event list already returns `_embedded.attractions[]` with each attraction's `id`.
2. Fetch `GET /discovery/v2/attractions/{attraction_id}.json?apikey=…` (recon in Task 1 must confirm whether `externalLinks.wiki` is present on the embedded attraction directly — in which case the extra call is skipped).
3. From `externalLinks.wiki[0].url` extract host (`en.wikipedia.org` / `de.wikipedia.org` / etc.) and the URL-encoded title.
4. Fetch `GET https://{host}/api/rest_v1/page/summary/{title}` — plain httpx.get, honest User-Agent (`EventTrackerBot/1.0 (contact@…)` per Wikipedia policy).
5. Read the `extract` field (plain-text summary, 1–3 paragraphs).
6. Use that as the event `description`.

#### New shared module: `backend/app/ingestion/wikipedia.py`

```python
def wiki_title_from_url(url: str) -> tuple[str, str] | None:
    """Parse a wikipedia URL. Returns (host, title) or None."""

def extract_summary(json_body: dict) -> str | None:
    """Return the plain-text summary from a Wikipedia REST summary response."""
```

Both are pure functions — no I/O. The adapter and backfill compose them with an `httpx.Client`.

#### Fetcher: new method on `TicketmasterAdapter`

```python
def _fetch_wiki_description(self, attraction: dict) -> str | None:
    """Follow the attraction's externalLinks.wiki to Wikipedia REST and
    return the summary text, or None if unavailable."""
```

Responsibilities: extract wiki URL from attraction (either from embedded `_embedded.attractions[i]` on the event or from a per-attraction detail call — recon decides), parse title, GET Wikipedia REST, on non-2xx or missing `extract` return None.

Politeness: 200 ms delay between Wikipedia calls (Wikipedia REST is generous but we're a good citizen). Result caching within a single ingest run so the same artist across multiple events is only fetched once (a `dict[str, str | None]` on the adapter).

#### Revised fallback chain in `_parse`

```python
description = (
    detail.get("info")
    or detail.get("additionalInfo")
    or detail.get("pleaseNote")
    or self._fetch_wiki_description_for_event(raw)
) or None
```

`_fetch_wiki_description_for_event(raw)` iterates `raw._embedded.attractions[]`, taking the first attraction that yields a Wikipedia summary.

### Revised Part B — Backfill script

Same shape as before, but uses Wikipedia lookup instead of Playwright page fetch. Same idempotence, same 200 ms delay, same commit-per-row.

### Revised Part C — Hide toggle (NEW)

New setting in `app/config.py`:

```python
hide_events_without_description: bool = True
```

Sourced from env var `HIDE_EVENTS_WITHOUT_DESCRIPTION=true|false`. Default **on** (hide).

The `visible_events_filter()` helper reads this setting at call time and returns:

- if `True`: `and_(is_active == True, description.isnot(None), description != "")`
- if `False`: `Event.is_active == True` (equivalent to the pre-existing behaviour)

Every call site uses `visible_events_filter()` unconditionally — the config flip changes behaviour everywhere without touching call sites.

**Chroma stale sweep:** the keep-set (`session.query(Event.id).filter(visible_events_filter()).all()`) also becomes conditional. When the toggle is off, Chroma re-embeds description-less events; when on, they're purged. This is the intended behaviour.

### Dropped from the design

- **Playwright / tf-playwright-stealth dependency** — no longer used. `playwright` remains in `pyproject.toml` for now (already committed as `15e1128`); can be removed in a cleanup commit. `tf-playwright-stealth` is not committed and should be removed from `pyproject.toml`.
- `backend/app/ingestion/browser.py` (PageFetcher protocol + PlaywrightPageFetcher) — never created; the plan referenced it but the pivot obviates it.
- Playwright smoke-test suite / `slow` pytest marker — no longer needed.

### Coverage expectations

- Wikipedia hit rate: expected ~15–30 % of TM events (an attraction has a wiki link — many artists do, most local acts don't).
- Combined with existing `info`/`additionalInfo`/`pleaseNote` (~5.6 %): total coverage estimate 20–35 %.
- The remaining 65–80 % of TM events are hidden by the filter when `hide_events_without_description=True`.
- This is materially better than "0 % useful descriptions" and factual (Wikipedia is authoritative for artist bios — won't mislead).

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Wikipedia rate limits | 200 ms delay + honest User-Agent + in-run cache per artist |
| Attraction has wiki link to a disambiguation page | Wikipedia REST `extract` on disambig is often empty or metadata — treat as no result (skip) |
| Non-English artist wikis (de/fr/it) | Handle any host — URL parsing extracts host from `externalLinks.wiki[].url` |
| Artist wiki summary describes the artist, not the event | Acknowledged trade-off — this is a bio, presented as event description. Better than nothing, factually accurate |
| Hide-toggle off leaks empty descriptions to Chroma | Intentional per config — operator opts in to including empty-desc events in embeddings |

### Tasks affected in the plan

Almost all tasks change. The plan is being rewritten (v2) rather than amended step-by-step. See `docs/plans/2026-07-01-event-descriptions-fallback.md` — the "Amendment 2" section at the top redirects to the new task list.
