# Eventim Adapter — Design

**Date:** 2026-07-07
**Status:** Draft
**Prior art:** `docs/Exploration.md` (Eventim section — probe from 2026-07-06)

## Problem

We want Hamburg concert coverage that the existing sources (Ticketmaster, hamburg_scraper, theater_hamburg, ohschonhell) don't reliably cover. Eventim's public JSON search API returns ~7,100 attend-once scheduled events for Hamburg across concerts, musicals/shows, cultural events, and sport — the largest single addressable source we've probed. Access is unauthenticated but fronted by Akamai, which sporadically 403s under load and could permanently ban clients that behave badly.

## Goal

Ship a new source adapter that ingests these ~7,100 events from Eventim's public search API into the existing pipeline, with:

- Field mapping matching the pipeline's `NormalizedEvent` conventions.
- Anti-bot resilience via bounded retries and a **manual-reset circuit breaker** so a bad day at Akamai can't compound into a permanent ban.
- Category mapping that produces a useful hint for the LLM categorizer.
- Test coverage that lets us change parser details without regressions.

## Non-Goals

- Cross-source deduplication of Eventim ↔ Ticketmaster / rausgegangen overlap — `dedup_events` already handles this generically post-upsert.
- Detail-page (`link` HTML) scraping for richer descriptions — Eventim's `/event/…` pages are behind Akamai Bot Manager and require a headless browser. Deferred to a separate spec.
- Wikipedia enrichment of Eventim `attractions[]` for missing descriptions — deferred; if we do it, it's a follow-up analogous to the TM/Wikipedia design (Amendment 2 of `2026-07-01-event-descriptions-fallback-design.md`).
- Auto-recovery of a tripped circuit breaker.
- Any city other than Hamburg (constant, not config).
- LLM-generated descriptions — explicitly disallowed pipeline-wide.

## Design Overview

New API adapter at `backend/app/ingestion/eventim.py` (top-level `ingestion/` per the API-vs-scraper split documented in `ingestion/CLAUDE.md`). Class `EventimAdapter` implements the `SourceAdapter` Protocol.

Per run: paginate four top-level Eventim categories (Konzerte, Musical & Show, Kultur, Sport) for `city_names=Hamburg`, parse each `product` into a `NormalizedEvent`, yield to the caller. Idempotence via existing `upsert_events`. No per-source cursor — the full crawl is cheap (~1 minute) and the API has no lastmod field to key delta off.

Anti-bot safety: retries on 403/429/503 with exponential backoff, plus a persistent circuit breaker that trips on sustained failure and refuses to hit the API until an operator manually resets it.

---

## Part A — Fetch and pagination

### Endpoint and query

```
GET https://public-api.eventim.com/websearch/search/api/exploration/v1/products
    ?city_names=Hamburg
    &categories=<category>
    &webId=web__eventim-de
    &language=de
    &page=<n>
    &top=50
    &sort=DateAsc
```

The API returns `totalPages` on every response. Adapter reads it from the page-1 response of each category and paginates 1..`totalPages`.

### Target categories

```python
_CATEGORIES = ["Konzerte", "Musical & Show", "Kultur", "Sport"]
```

Expected counts (probed 2026-07-07): Konzerte 1,819 · Musical & Show 4,299 · Kultur 981 · Sport 27 = **~7,100 events**.

Deliberately excluded: **Freizeit** (14,455 harbor-tour/museum-ticket rows — permanent tourism catalog, not attend-once events) and **VIP & Extras** (1,696 add-ons that duplicate Konzerte rows).

### HTTP client

`httpx.Client(timeout=20, headers=_DEFAULT_HEADERS)`. The default headers set is the Akamai-friendly set proven by `probe_eventim.py`: User-Agent (Chrome-shaped), `Origin: https://www.eventim.de`, `Referer: https://www.eventim.de/city/hamburg-72/`, `Accept-Language: de-DE,de;q=0.9,en;q=0.8`, `Sec-Ch-Ua*`, `Sec-Fetch-*`. Minimal-header requests get `403 Access Denied` from the edge, so this set is mandatory.

The client is instantiated in `__init__` and stays alive for the adapter's lifetime (matches `TicketmasterAdapter`).

### Politeness

`_REQUEST_DELAY_SECONDS = 0.2` between pages, injected via `sleep_fn` so tests can monkeypatch it to a no-op.

Total wall-clock estimate for a healthy run: ~160 pages × 200ms delay + HTTP round trips ≈ 60–90 seconds.

### Failure escalation (per run, not persistent)

- Retries exhausted on a mid-category page → log WARNING, skip the page, continue.
- Retries exhausted on page 1 of a category (needed for `totalPages`) → log WARNING, skip the whole category, continue.
- All four categories fail page 1 → raise `RuntimeError("eventim: all categories failed page 1")` so the scheduler surfaces it. This is a hard fail — the scheduler's per-adapter try/except catches it and continues with other adapters.

The persistent circuit breaker (Part C) sits on top of this — sustained failure across the run trips a durable "disabled" flag.

---

## Part B — Parsing

### Pure extractor

```python
def parse_product(product: dict) -> NormalizedEvent | None:
    """Convert one Eventim product to a NormalizedEvent, or None if unusable."""
```

No I/O, no session — pure `dict → NormalizedEvent | None`. This is the unit-testable core of the adapter.

### Field mapping

| `NormalizedEvent` | Eventim source | Notes |
|---|---|---|
| `external_id` | `productId` (str) | Unique per date. Multiple tour dates share `productGroupId`; we key on `productId` so each date is its own row. |
| `source` | `"eventim"` | |
| `title` | `name` | |
| `description` | `description` | ~50% coverage on Konzerte. `None` when absent → hidden by `visible_events_filter` (accepted MVP tradeoff). |
| `summary` | `None` | Dead field per `ingestion/CLAUDE.md`. |
| `start_datetime` | `typeAttributes.liveEntertainment.startDate` | ISO 8601 with tz offset (e.g. `2026-10-12T20:00:00+02:00`) → aware datetime. |
| `end_datetime` | `None` | Not in payload. |
| `venue_name` | `typeAttributes.liveEntertainment.location.name` | |
| `venue_address` | `f"{postalCode} {city}"` | Eventim payload has no street address. |
| `latitude` / `longitude` | `location.geoLocation.{latitude,longitude}` | |
| `category` | Sub-level `categories[]` name → `_CATEGORY_MAP` (see Part D) | Adapter hint; LLM categorizer refines. |
| `tags` | Top-level Eventim category + leaf category + `[a.name for a in attractions]` | Artist names + Eventim's own category strings for recommender input. |
| `price_min` | `price` | Eventim ships only a starting price. |
| `price_max` | `None` | Unknown ceiling — honestly nullable rather than misleading. |
| `is_free` | `price == 0` | |
| `currency` | `currency` (usually `"EUR"`) | |
| `image_url` | `imageUrl` | 222x222 teaser jpg. |
| `source_url` | `link` | Canonical event page URL. |
| `raw_data` | `{"productId", "productGroupId", "eventim_categories": [...], "startDate_raw": "..."}` | Diagnostic; nothing in the runtime reads it. |

### Rejection rules

`parse_product` returns `None` (and logs at DEBUG) for:

- Missing any of `productId`, `name`, or `typeAttributes.liveEntertainment.startDate` — structural required fields.
- `type != "LiveEntertainment"` — guards against Freizeit rows leaking via cross-tagging.
- `location.city != "Hamburg"` — paranoid guard; the query filters by city but Eventim occasionally returns near-matches (e.g. Hamburg district names).

Rejected rows do not block the rest of the batch.

---

## Part C — Retry and circuit breaker

Two independent mechanisms:

1. **Per-request retry** (transient) — handles isolated 403/429/503 responses within a single call.
2. **Circuit breaker** (persistent) — sits above the retry layer, trips on sustained failure, requires manual reset. Prevents auto-recovery from compounding into a permanent ban.

### Per-request retry helper (local to `eventim.py`)

```python
_RETRY_STATUS_CODES = {403, 429, 503}
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BASE_SLEEP = 2.0  # exponential: 2s, 4s, 8s

@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0
    akamai_403s: int = 0
    akamai_refs: list[str] = field(default_factory=list)  # capped at 5

def get_json_with_retry(client, url, params, *, stats, sleep_fn) -> dict | None:
    """GET a JSON endpoint with exponential backoff. On 403, extract Akamai
    Reference IDs from the body via regex ('Reference #<hex>') and record up
    to 5 in stats.akamai_refs for diagnostics. Returns parsed JSON or None."""
```

Differences from `ohschonhell.get_with_retry`:

- Retriable set = `{403, 429, 503}` (403 added).
- 4 attempts (vs. 3) and 2s base sleep (vs. 1s) — Akamai blocks tend to hold longer than generic 429/503.
- Returns parsed JSON dict, not raw text.
- Records Akamai Reference IDs when present so we can spot fingerprint drift.

### Circuit breaker (persistent state on `IngestionState`)

New columns on `ingestion_states` (see Part E for migration):

- `disabled_at TIMESTAMP NULL`
- `disabled_reason VARCHAR NULL`
- `runs_while_disabled INTEGER NOT NULL DEFAULT 0`

Adapter checks the state at the top of `fetch()`. If tripped: increment `runs_while_disabled`, emit a multi-line WARNING banner (below), return without any HTTP call.

**Trip conditions** — any one of these during a run:

| Condition | Threshold | Reason string |
|---|---|---|
| Consecutive per-page retry-exhaustion | ≥ 3 pages | `consecutive_retry_exhaustion: 3 pages` |
| All four categories fail page 1 with retry-exhaustion | 4/4 | `all_categories_failed_page_1` |
| Total 403 events (across all attempts) | ≥ 15 | `total_403_budget_exceeded: 15` |

On trip: set `disabled_at = now`, `disabled_reason = <string>`, **commit the trip state to its own transaction** (open a fresh short-lived session for this write, not the ingestion session), then stop the fetch by returning normally. Everything already yielded before the trip has been persisted by the caller. The dedicated commit is deliberate — the ingestion pipeline's usual transaction discipline says stages don't commit, but here the whole point is that the trip state must survive even if the surrounding `run_ingestion` transaction later rolls back for an unrelated reason. Losing the trip flag would mean auto-recovery on the next run, exactly what we're preventing.

### Banner formatting

Already-tripped run (first log line of `fetch()`):

```
!! ============================================================
!! EVENTIM ADAPTER DISABLED
!!   Tripped at:  <ISO timestamp>
!!   Reason:      <reason string>
!!   Runs since:  <runs_while_disabled>
!!   To re-enable: python -m scripts.reset_adapter_lock eventim
!! ============================================================
```

Mid-run trip:

```
!! ============================================================
!! EVENTIM CIRCUIT BREAKER TRIPPED THIS RUN
!!   At:       <ISO timestamp>
!!   Reason:   <reason string>
!!   Partial:  ingested <N> events from <category> before trip
!!   Skipped:  <remaining categories>
!!   Reset:    python -m scripts.reset_adapter_lock eventim
!! ============================================================
```

WARNING level in both cases. Banner is re-emitted every run — no deduplication.

### Scheduler summary line

`scheduler.py` prints a per-adapter summary at the end of the run. For a tripped Eventim adapter:

```
eventim        : *** SKIPPED - CIRCUIT BREAKER TRIPPED *** (see WARNING above)
```

The `*** SKIPPED ***` marker is a distinct string designed to stand out in both a live-tail terminal and `grep`.

### Manual reset

New script `backend/scripts/reset_adapter_lock.py`:

```
python -m scripts.reset_adapter_lock <source>
```

Prints the current trip state (timestamp, reason, `runs_while_disabled`), asks for confirmation, clears `disabled_at`, `disabled_reason`, and `runs_while_disabled` on the named source's `IngestionState` row.

- `--yes` flag skips confirmation (for tests).
- Non-existent source name → error + exit 1.
- No trip state to clear (row exists but `disabled_at` is NULL) → info message + exit 0.

Generic in the source name — same script will work for future adapters that adopt the same pattern.

---

## Part D — Category mapping

Static dict keyed on the leaf category name (the `categories[]` entry whose `parentCategory` is populated):

```python
_CATEGORY_MAP: dict[str, EventCategory] = {
    # Konzerte subcategories → concerts
    "Rock & Pop": "concerts",
    "HipHop & R'n'B": "concerts",
    "Schlager & Volksmusik": "concerts",
    "Jazz & Blues": "concerts",
    "Elektronische Musik": "concerts",
    "Metal & Hardrock": "concerts",
    "Weitere Konzerte": "concerts",
    # Kultur subcategories
    "Klassische Konzerte": "concerts",
    "Oper": "theater",
    "Ballett & Tanz": "theater",
    "Theater": "theater",
    # Musical & Show subcategories
    "Musical": "theater",
    "Show": "other",
    # Sport subcategories
    "Fußball": "sports",
    "Handball": "sports",
    "Weitere Sportarten": "sports",
}
```

Unknown leaves fall back to `"other"` **and log a WARNING** with the leaf name so we notice new categories drift into the source. The LLM categorizer runs after this and treats the hint as advisory — anything wrong here gets corrected downstream.

Plan Task 1 (recon): paginate all four categories once and log the union of encountered leaf names. Use the output to fill any gaps in `_CATEGORY_MAP` before merging.

---

## Part E — Migration and file map

### Migration

New alembic revision `0008_ingestion_state_circuit_breaker` adds three columns to `ingestion_states`:

- `disabled_at TIMESTAMP NULL`
- `disabled_reason VARCHAR NULL`
- `runs_while_disabled INTEGER NOT NULL DEFAULT 0`

Existing rows get `NULL` / `0`. Reversible. SQLite-safe.

Also update `app/db/models/ingestion_state.py` with the mapped columns.

### File map

| Action | Path |
|---|---|
| Create | `backend/app/ingestion/eventim.py` |
| Create | `backend/scripts/reset_adapter_lock.py` |
| Create | `backend/app/db/migrations/versions/0008_ingestion_state_circuit_breaker.py` |
| Modify | `backend/app/db/models/ingestion_state.py` (new columns) |
| Modify | `backend/app/ingestion/scheduler.py` (register `EventimAdapter`, add `*** SKIPPED ***` summary line) |
| Create | `backend/tests/ingestion/test_eventim.py` |
| Create | `backend/tests/ingestion/fixtures/eventim/*.json` (real-shape captures) |
| Create | `backend/tests/scripts/test_reset_adapter_lock.py` |
| Modify | `backend/tests/ingestion/test_scheduler.py` (add tripped-summary test) |

---

## Part F — Testing

### Unit tests — `test_eventim.py`

Parser (`parse_product`):

- Full fixture → every `NormalizedEvent` field mapped correctly.
- Missing `description` → `description is None`, rest of event intact.
- Missing `geoLocation` → `latitude` / `longitude` are `None`.
- Missing required (`productId` / `name` / `startDate`) → returns `None`.
- `type="Package"` (Freizeit shape) → returns `None`.
- `location.city="Berlin"` → returns `None`.

Category mapping:

- Every entry in `_CATEGORY_MAP` yields its declared `EventCategory`.
- Unknown leaf → `"other"` AND WARNING logged.
- Tags include artist names AND both Eventim category strings.

Price mapping:

- `price=42.5` → `price_min=42.5`, `price_max=None`, `is_free=False`.
- `price=0` → `is_free=True`.

Retry helper (`get_json_with_retry`):

- 403 → 403 → 200: success, `stats.total_retries == 2`.
- 4× 403: returns `None`, `stats.exhausted == 1`, `stats.akamai_403s == 4`.
- 404: no retry, returns `None`.
- 403 body contains `"Reference #abc123"`: captured in `stats.akamai_refs`.

Circuit breaker:

- Row with `disabled_at` set → `fetch()` yields nothing AND makes zero HTTP calls (assertion via fake client that raises on any GET).
- 3 consecutive per-page retry-exhaustions → trips with reason `consecutive_retry_exhaustion: 3 pages`.
- All 4 categories fail page 1 with retry-exhaustion → trips with reason `all_categories_failed_page_1`.
- 15 scattered 403s → trips with reason `total_403_budget_exceeded: 15`.
- Two consecutive `fetch()` calls while tripped → `runs_while_disabled` goes 0 → 1 → 2.
- Banner substrings present in log output (`"EVENTIM ADAPTER DISABLED"`, reason string, reset command).

Pagination:

- 4 categories × 3 pages each → exactly 12 GET calls, product order preserved.
- Page 2 retry-exhausted → pages 1 and 3 events still yielded.

### Integration test — `test_reset_adapter_lock.py`

- Seed `IngestionState("eventim")` with all three columns set → run script `main(["eventim", "--yes"])` → assert all three cleared.
- Non-existent source arg → error message, exit 1.
- Row exists but `disabled_at` is `NULL` → info message, exit 0.

### Scheduler integration — extend `test_scheduler.py`

- Register a mocked adapter marked tripped → assert final summary line contains `*** SKIPPED - CIRCUIT BREAKER TRIPPED ***`.

### Fixture strategy

Fixtures under `backend/tests/ingestion/fixtures/eventim/` are minimal-shape captures from `probe_eventim.py --dump`, hand-trimmed to remove noise while preserving structure. Cover: full-featured Konzerte event, no-description event, non-Konzerte (Kultur → Klassische Konzerte), Freizeit leakage (rejected by type check).

---

## Success criteria

- Fresh DB, empty `IngestionState`: single run produces ~7,100 rows with `source="eventim"`, ~48% with non-null `description`.
- Category distribution roughly matches probed counts (Konzerte ~1,819, Musical & Show ~4,299, Kultur ~981, Sport ~27).
- No row has NULL `title`, `start_datetime`, `venue_name`, or `source_url`.
- Re-run produces zero new rows; almost all rows `updated`.
- `python -m scripts.reset_adapter_lock eventim` clears trip state on demand.
- All new tests pass; existing tests continue to pass.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Eventim's leaf category set changes | Unknown-leaf fallback → `"other"` + WARNING log |
| Akamai fingerprint drift causes sustained 403 | Circuit breaker + manual reset; Reference IDs logged for header-refresh diagnostics |
| `productId` semantics change (rare) | Composite key `(external_id, source)` regression would surface as duplicate rows on next run — noticeable |
| Missing `productId` on some products | Rejected by `parse_product`; DEBUG log; other events unaffected |
| Freizeit rows leak into a targeted category via cross-tagging | `type != "LiveEntertainment"` guard rejects them |
| Operator resets breaker without fixing headers → immediate re-trip | Reset script prints the trip reason and asks for confirmation, explicitly reminding operator to verify headers first |
| Trip persists silently across runs | Banner emitted every run + scheduler summary line `*** SKIPPED ***` + `runs_while_disabled` counter in banner |
| Partial ingest state on mid-run trip | Yield-what-we-had before tripping; existing upsert commits are per-run so the partial batch is persisted; next healthy run's full crawl is idempotent over it |

---

## Constants block (reference, not authoritative)

Actual values in code will live in `eventim.py`:

```python
_API = "https://public-api.eventim.com/websearch/search/api/exploration/v1/products"
_CITY = "Hamburg"
_CATEGORIES = ["Konzerte", "Musical & Show", "Kultur", "Sport"]
_TOP = 50
_REQUEST_DELAY_SECONDS = 0.2
_RETRY_STATUS_CODES = {403, 429, 503}
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BASE_SLEEP = 2.0
_TRIP_CONSECUTIVE_EXHAUSTIONS = 3
_TRIP_TOTAL_403_BUDGET = 15
```

Tests monkeypatch these where needed.
