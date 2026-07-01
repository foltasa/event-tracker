# Event Descriptions — Ticketmaster Page Scrape + Hide-Empty Design

**Date:** 2026-07-01
**Status:** Approved (brainstorming), pending user spec review

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
