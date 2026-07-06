# ohschonhell.de Scraper + Ingestion State Store Design

**Date:** 2026-07-06
**Status:** Approved — proceeding to plan.

## Problem

The ingestion pipeline currently covers Ticketmaster, heuteinhamburg.de, and
theater-hamburg.org. All three lean toward theater, opera, and general
"what's on today" listings. Party events (club nights, techno raves, open-airs)
are severely underrepresented — the user's catalog reflects this.

ohschonhell.de is Hamburg's canonical party listing. A probe run against
20 recent events showed 100% coverage on `name`, `startDate`, `location_name`,
and full address; 95% coverage on `description` (with variable length from
5 chars — "LEHAR" — to 1783 chars for festival press releases). All data is
exposed as schema.org/Event microdata on `/date/{slug}` pages. No API,
no bot challenges, no CAPTCHA at Cloudflare-frontend.

Fetching every detail page on every run is impractical: the site's current
sitemap file (`post-sitemap26.xml`) contains ~1000 URLs. A per-run delta
strategy is required, which in turn needs persistent state — a concept the
existing scrapers don't have. This design introduces both.

## Goal

Ingest Hamburg party events from ohschonhell.de as a new source, keyed by
the WordPress-internal event ID for stability against slug edits. Use a
sitemap-delta strategy backed by a new generic `ingestion_state` table so
the pipeline can run at any cadence — including catch-up after multi-day
gaps — without missing or double-fetching events. Add pipeline-wide
progress logging so long runs are observable.

## Non-Goals

- Other ohschonhell cities (Berlin, Köln, Stuttgart, RheinMain, Thüringen,
  Wien, CapeTown). The subdomains use the same code path and can be
  registered later as additional adapter instances — out of scope here.
- Migrating existing scrapers (`hamburg`, `theater_hamburg`, `ticketmaster`)
  onto the new state store. The store is generic and open for reuse, but
  those adapters ship unchanged in this iteration.
- All-day events. Events without a display-text time are skipped and
  logged. Extending the data model (`is_all_day` field, frontend rendering)
  is deferred as a separate future feature.
- Adaptive rate limiting, circuit breakers, or persistent retry queues.
  A fixed 150 ms delay + 3-attempt exponential backoff is sufficient
  for observed traffic.
- Artist / DJ extraction into `tags`. Description text is unstructured;
  reliable parsing is out of scope.
- Price / `is_free` inference. The source has no structured price info.

## Design Overview

Four coordinated pieces:

**A.** New `ingestion_state` table + `state.py` helper module. Generic
key-value store keyed by `source`, holding `last_seen_lastmod`. Consumed
by ohschonhell now, reusable by other scrapers later.

**B.** New `OhschonhellScraper` in
`backend/app/ingestion/scrapers/ohschonhell.py`. Sitemap-delta discovery,
per-event detail fetch, microdata parsing, retry-backoff. Registered
next to existing adapters in `_default_adapters()`.

**C.** Scheduler cross-cut logging. Per-adapter start/end/duration lines
and pipeline-stage markers (`fetch`, `categorization`, `upsert`, `dedup`,
`embedding`). Applies to every adapter, not just the new one.

**D.** Fixture-based tests for parser, sitemap filter, state helpers,
adapter end-to-end with `_FakeClient`, and the new scheduler logs.

---

## Part A — `ingestion_state` Table + `state.py`

### Schema

New SQLAlchemy model at `backend/app/db/models/ingestion_state.py`:

```
class IngestionState(Base):
    __tablename__ = "ingestion_state"
    source: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen_lastmod: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

One row per source. `source` is a free-form string matching an adapter's
`name` field (e.g. `"ohschonhell"`).

### Alembic Migration

Auto-generated. Named `0009_ingestion_state.py` (or whatever the next
sequential number is). `CREATE TABLE` + `DROP TABLE` on downgrade.

### Helper Module

`backend/app/ingestion/state.py`:

- `get_last_seen(session, source: str) -> datetime | None`
- `set_last_seen(session, source: str, ts: datetime) -> None`

Both operate on the caller's session without committing. `set_last_seen`
overwrites unconditionally — no max-comparison. The adapter is responsible
for the semantics of what `ts` means.

---

## Part B — `OhschonhellScraper`

### Constants

```
_SITEMAP_URL = "https://ohschonhell.de/post-sitemap26.xml"
_BASE_URL    = "https://ohschonhell.de"
_BERLIN      = ZoneInfo("Europe/Berlin")
_UA          = "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"
_BOOTSTRAP_WINDOW_DAYS = 90
_REQUEST_DELAY_SECONDS = 0.15
_RETRY_STATUS_CODES = {429, 503}
_RETRY_MAX_ATTEMPTS  = 3
_RETRY_BASE_SLEEP    = 1.0   # 1s, 2s, 4s exponential
_PROGRESS_INTERVAL_SECONDS = 30
```

Sitemap file number (`26`) is hardcoded intentionally. When the site rolls
over to `post-sitemap27.xml`, we adjust — cheaper than parsing the sitemap
index every run.

### Discovery

1. Fetch `_SITEMAP_URL` once. Parse `<url>` entries.
2. Determine cutoff:
   - If `get_last_seen(session, "ohschonhell")` returns `None` (bootstrap):
     cutoff = `now(UTC) - 90 days`
   - Else: cutoff = returned timestamp
3. Filter entries where `<loc>` matches `/date/` AND `<lastmod>` > cutoff.
4. Sort ascending by `lastmod` so the highest processed lastmod is the
   final one committed to state.

### Per-Event Extraction

For each candidate URL:

1. Sleep `_REQUEST_DELAY_SECONDS` (skip on first iteration).
2. GET the detail page with retry-backoff (see Fault-Handling).
3. Decode with `resp.content.decode("utf-8", errors="replace")`.
4. Parse with BeautifulSoup, extracting the schema.org/Event microdata:
   - `event_id` — regex `eventId=(\d+)` on the raw HTML
   - `name` — `itemprop=name` direct child of `itemtype=schema.org/Event`
   - `date` — `itemprop=startDate content="…"` (ISO date)
   - `time` — regex `\b(\d{1,2}):(\d{2})\b` on the display text of the
     `startDate` element
   - `description` — `itemprop=description`, joined with separator `" "`
     to break up glued-together lineup names
   - `venue_name` — nested `itemprop=name` under `itemtype=schema.org/Place`
   - `street`, `postalCode`, `city` — nested itemprops under
     `itemtype=schema.org/PostalAddress`
   - `image_url` — `<meta property="og:image" content="…">`
5. If `event_id`, `name`, `date`, `time`, or `venue_name` is missing:
   log `WARNING`, skip event, continue to next URL.
6. Otherwise build `NormalizedEvent`.

### Field Mapping to `NormalizedEvent`

| Field | Value |
|---|---|
| `external_id` | `event_id` (string) |
| `source` | `"ohschonhell"` |
| `title` | `name` |
| `description` | `description` or `None` (no length filter) |
| `start_datetime` | `datetime(date + time, tzinfo=_BERLIN)` |
| `end_datetime` | `None` |
| `venue_name` | `venue_name` |
| `venue_address` | `f"{street}, {postalCode} {city}"` |
| `latitude` / `longitude` | `None` |
| `category` | `"party"` (LLM classifier refines) |
| `tags` | `["party"]` |
| `is_free` | `False` |
| `price_min` / `price_max` | `None` |
| `currency` | `"EUR"` (default) |
| `image_url` | `og:image` value or `None` |
| `source_url` | sitemap `<loc>` |
| `raw_data` | `{"event_id": …, "slug": …, "sitemap_lastmod": …}` |

### State Update

After the fetch iterator has yielded all successful events, the adapter
calls `set_last_seen(session, "ohschonhell", max_lastmod)` where
`max_lastmod` is the highest sitemap `<lastmod>` among **successfully
processed events** (not the sitemap max, so skipped events remain
in-scope for the next run's delta).

Commit semantics: the adapter does not commit. The scheduler's existing
`session.commit()` at the end of `run_ingestion` commits state and events
atomically. If any downstream stage (`dedup`, `embedding`) fails, both
roll back — the next run re-processes the delta from the previous
committed state.

### Session Injection

`OhschonhellScraper.__init__` accepts an optional `client: httpx.Client`
(as existing adapters do) and an optional `sleep_fn` (defaults to
`time.sleep`) for test injection. Session is passed to `.fetch()` as an
argument — this is a signature change from the current `Iterator[NormalizedEvent]`
protocol.

**Signature change**: `SourceAdapter.fetch(session)` — the state store
needs DB access. The `SourceAdapter` Protocol in `base.py` is updated
accordingly. All three existing adapters (`TicketmasterAdapter`,
`HamburgScraper`, `TheaterHamburgAdapter`) get their `fetch` signatures
updated to accept the session argument and ignore it. The scheduler's
`adapter.fetch()` call becomes `adapter.fetch(session)`. This is a
mechanical, one-line-per-adapter change. Adapters that don't need
state simply don't call `state.py`.

---

## Part C — Scheduler Cross-Cut Logging

Modify `backend/app/ingestion/scheduler.py`:

### Per-Adapter Lifecycle

```
logger.info("[%s] fetch starting", adapter.name)
t0 = time.monotonic()
try:
    batch = list(adapter.fetch(session))
    logger.info("[%s] fetched %d events in %.1fs", adapter.name, len(batch), time.monotonic() - t0)
except Exception:
    logger.exception("[%s] fetch failed after %.1fs", adapter.name, time.monotonic() - t0)
```

### Pipeline Stages

Log-line before each stage of `run_ingestion`:

- `logger.info("stage: fetch (%d sources)", len(adapters))`
- `logger.info("stage: categorization (%d events)", len(all_events))`
- `logger.info("stage: upsert")`
- `logger.info("stage: dedup")`
- `logger.info("stage: embedding")`

### Progress Heartbeat (in Ohschonhell Adapter, not Scheduler)

Every 30 wall-clock seconds during the detail-fetch loop, log
`ohschonhell: progress %d/%d fetched (%d%%)` even if no new event was
processed in the interval. Implemented inline via a `last_log_at`
timestamp checked at the top of each loop iteration.

### Retry Summary

At the end of the adapter run, if any retries occurred, log
`ohschonhell: N retries encountered (avg backoff: T.Ts)`. This surfaces
whether the fixed 150 ms delay is holding up without needing to grep for
individual WARNING lines.

### Adapter Summary Line

Also at the end, log
`ohschonhell: N candidates → M parsed, K skipped (missing time: X, parse error: Y, retries exhausted: Z)`.
Sudden drops in the parse-rate are the earliest signal that the source's
HTML structure changed.

---

## Fault-Handling

### Sitemap Unreachable

Adapter propagates the exception. Scheduler's existing `try/except`
(around line 107) catches it, logs `[ohschonhell] fetch failed after T.Ts`,
proceeds with other adapters. State is never updated. Next run retries
the delta from the same `last_seen_lastmod`.

### Detail Page — Transient (5xx, timeout)

Same retry-backoff as 429/503 (see below).

### Detail Page — 429 / 503

Exponential backoff: 1s, 2s, 4s. After 3 failed attempts, log
`WARNING ohschonhell: giving up on {url} after 3 attempts`, skip event,
continue. The event's `lastmod` is NOT included in the running
`max_lastmod` for state — next run will find it again.

### Detail Page — Parse Error

Log `WARNING ohschonhell: parse failed for {url}: missing {field} — skipping`.
Same handling as retry-exhausted: skip, don't advance state past its `lastmod`.

### Detail Page — Missing Time

Log `WARNING ohschonhell: no start time on {url} — skipping`. Same
handling: skip, don't advance state.

### Encoding Anomalies

Never crash on bad bytes. `resp.content.decode("utf-8", errors="replace")`
substitutes `�` for unrepresentable sequences. Downstream parsing
handles replacement chars gracefully — worst case, one field is garbled
and downgrades description quality by one event.

---

## Part D — Tests

New file: `backend/tests/ingestion/test_ohschonhell.py`.

### Fixtures

Real snapshots committed under `backend/tests/fixtures/`:

- `ohschonhell_sitemap_sample.xml` — trimmed sitemap with ~5 `<url>` entries
  spanning varied `lastmod` values, including one before a "cutoff" the
  filter tests use
- `ohschonhell_event_full.html` — a well-populated detail page
- `ohschonhell_event_minimal.html` — a "DJ-name only" description page

### Test Cases

**Parser (pure function, offline):**

1. Full page → all fields correctly mapped, `start_datetime` is TZ-aware
   in Berlin time, `venue_address` is comma-joined
2. Minimal page → parses successfully, `description` remains short
3. Missing time on display text → parser signals skip (returns `None`
   or raises a sentinel)
4. Missing `event_id` → parser signals skip
5. Umlauts in name/address → correctly decoded (no `�`)

**Sitemap Filter:**

6. Bootstrap (no `last_seen`) → filters entries with `lastmod > now - 90d`
7. Delta (with `last_seen`) → filters `lastmod > last_seen`, no duplicates

**Adapter End-to-End with `_FakeClient`:**

8. Bootstrap: 3 URLs in sitemap → 3 events yielded, `set_last_seen` called
   with the highest lastmod among yielded events
9. Delta: 5 URLs, 2 with `lastmod > last_seen` → only 2 events yielded
10. Retry: first response 429, second 200 → event still yielded, WARNING
    logged, retry counter incremented
11. Retry exhausted: 3× 429 → event skipped, WARNING with URL logged,
    `state` not advanced past this URL's `lastmod`
12. Parse error mid-batch: 3 URLs, middle one broken HTML → 2 events
    yielded, no crash, WARNING logged
13. Skip missing time → event not yielded, WARNING logged

**State Helper (`state.py`):**

14. `get_last_seen` on empty table → `None`
15. `set_last_seen` then `get_last_seen` → roundtrip correct, TZ-aware
16. `set_last_seen` with older timestamp overwrites unconditionally

**Scheduler Cross-Cut (extending `test_scheduler.py`):**

17. `run_ingestion` with a fake adapter yielding 3 events → INFO log
    includes `[fake] fetch starting`, `[fake] fetched 3 events in T.Ts`,
    and all `stage: …` markers

### Not Tested

- Live requests against ohschonhell.de
- Alembic migration itself (verified implicitly by test DB setup)
- 150 ms sleep timing (mocked via `sleep_fn` injection)

---

## Adapter Registration

`backend/app/ingestion/scheduler.py`, `_default_adapters()`:

```
return [
    TicketmasterAdapter(wiki_client=wiki_client),
    HamburgScraper(),
    TheaterHamburgAdapter(),
    OhschonhellScraper(),
]
```

Order does not matter for correctness — each adapter runs in isolation.
Alphabetical / thematic grouping is a stylistic choice.

---

## Rollout

1. Ship migration + state helper (safe, additive, unused).
2. Ship OhschonhellScraper + tests.
3. First scheduled run performs bootstrap: fetches ~600 events over
   ~90 seconds with 150 ms delay, writes state, upserts, categorizes,
   embeds. Total added time: ~2 minutes.
4. Subsequent runs are delta-only, negligible added time.

No feature flag. If the run fails, existing adapters still run
(scheduler-level try/except), and the migration is idempotent (rollback
via Alembic downgrade if needed).
