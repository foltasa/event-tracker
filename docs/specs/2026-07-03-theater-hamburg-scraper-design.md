# Theater-Hamburg Scraper + Post-Ingest Dedup Design

**Date:** 2026-07-03
**Status:** Approved — proceeding to plan.

## Problem

Ticketmaster covers 337 Hamburg events; after the Wikipedia-summary fallback we expect 20–35 % description coverage. Everything else is hidden by `hide_events_without_description`. The user sees a nearly empty catalog.

The `imxplatform` widget behind `theater-hamburg.org/theater-hamburg/spielplan/` exposes ~1969 upcoming Hamburg cultural events (theater, opera, concerts at Elphi/Laeiszhalle/Staatsoper, etc.), **all with `shortDescription` populated**, via a single GraphQL endpoint reachable with plain httpx. Adding it as an event source raises visible coverage from a few dozen to ~2000 events, nearly all with real, editorial descriptions.

## Goal

Ingest theater-hamburg.org events (via the imxplatform GraphQL API) as a new event source and deduplicate against existing Ticketmaster / heuteinhamburg.de rows so the same show doesn't appear twice. The theater-hamburg row wins on collision because its descriptions are consistently better.

## Non-Goals

- Abstract "family-of-scrapers-by-tech-style" base class. Deferred until a second same-style site exists (YAGNI).
- Adding more aggregator sites in this iteration. One adapter, one site.
- Changes to the TM Wikipedia fallback. Runs unchanged in parallel.
- Fuzzy-title matching as the primary dedup key. Used only as a safety net.
- New DB columns (`source_priority`). Priority lives in the dedup module.

## Design Overview

Three coordinated pieces:

**A.** New `TheaterHamburgAdapter` in `backend/app/ingestion/scrapers/theater_hamburg.py`, structured like `TicketmasterAdapter` (list + per-item detail fetch, per-run caching). Talks GraphQL to `content-delivery.imxplatform.de/hht/imxplatform` with a Bearer JWT scraped from the public widget bundle at init.

**B.** New `dedup_events(session)` function in `backend/app/ingestion/dedup.py`. Runs post-ingest in its own transaction. Groups active events by `(normalized venue, start_datetime bucket, title-jaccard clique)`, picks the highest-priority winner, migrates `saved_events` foreign keys, deletes losers. Idempotent.

**C.** Scheduler wiring: register the new adapter in `_default_adapters()`, call `dedup_events()` at the end of `run_ingestion` after all adapters complete.

Chroma stale-vector cleanup (existing) picks up the deleted losers on the next embed run.

---

## Part A — `TheaterHamburgAdapter`

### Endpoint

- URL: `POST https://content-delivery.imxplatform.de/hht/imxplatform`
- Headers: `Authorization: Bearer <JWT>`, `Content-Type: application/json`.
- Body: standard GraphQL `{"query": "...", "variables": {...}}`.

### JWT acquisition

The JWT is baked into the public widget bundle at `https://hht.whitelabel.imxplatform.de/widget/widget.js`. It has no `exp` claim — appears long-lived — but we treat it as rotatable:

- On adapter init: GET the widget.js URL, regex-extract the JWT (`ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`), cache on the instance.
- On any 401 response: re-scrape once, retry the failing request once. If it 401s again → raise.
- Escape hatch: env var `THEATER_HAMBURG_JWT` overrides scraping (opt-in, for the day the JS URL moves).

### List query — `EventSearch`

Whitelabel scoping filter is copied verbatim from the widget (fixed set of ~35 `eventLocation.id`s + 15 `group`s, all Hamburg venues) plus `fromDate: today`.

```graphql
query EventSearch($filter: EventFilter!, $pagination: PaginationInput!, $appearance: AppearanceInput!) {
  events(filter: $filter, pagination: $pagination, appearance: $appearance) {
    nodes {
      id
      title
      permaLink
      categories { title }
      contact { location { id title } }
      eventDates { date startTime duration }
      geoInfo { latitude longitude }
      image { deeplink }
      bookingLink
    }
    pagination { totalPages totalRecords }
  }
}
```

Pagination: `pageSize=1000`, 2 calls at current volume. `appearance.deliveryChannel = 76` mandatory.

Each returned `node` yields one candidate event per entry in `eventDates` (a show with 5 upcoming performances = 5 `NormalizedEvent`s sharing `permaLink`).

### Detail query — `EventDetails`

Per `permaLink`, one call:

```graphql
query EventDetails($permalink: String!) {
  events(filter: {permaLink: {eq: $permalink}}) {
    nodes { shortDescription }
  }
}
```

`shortDescription` is HTML. Strip with `BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)`.

Cache per `permaLink` within a run — 1969 dates typically span ~600 unique shows, so ~3× dedup on detail calls.

### Rate limiting

200 ms delay between detail calls (module constant so tests can monkeypatch to 0). Total ingest time: ~2 min for detail fetches at typical show count. No delay on list calls (only 2).

### Mapping to `NormalizedEvent`

| Field | Source |
|---|---|
| `external_id` | `f"{permaLink}#{eventDate.date}T{eventDate.startTime}"` (stable per date) |
| `source` | `"theater_hamburg"` |
| `title` | `node.title` |
| `description` | detail `shortDescription` → HTML-stripped |
| `start_datetime` | `f"{eventDate.date}T{eventDate.startTime}"` parsed into Europe/Berlin |
| `venue_name` | `node.contact.location.title` |
| `venue_address` | `None` (not in schema; can be added later) |
| `latitude`/`longitude` | `node.geoInfo.latitude`/`.longitude` if present |
| `category` | first category title, mapped via existing category map (extend if needed) |
| `tags` | remaining category titles, lowercased |
| `price_min`/`price_max`/`is_free`/`currency` | `None`/`None`/`False`/`"EUR"` for v1 (pricing fields in schema; skip until needed) |
| `image_url` | `node.image.deeplink` |
| `source_url` | `f"https://theater-hamburg.org/theater-hamburg/veranstaltung/{permaLink}/"` (URL pattern to confirm during implementation via one live check) |
| `raw_data` | full node + detail JSON (kept for future backfill / debugging) |

Skipping malformed rows follows the same `except (KeyError, ValueError, TypeError)` pattern as the other adapters — log + skip, don't halt the ingest.

---

## Part B — Dedup module

### `backend/app/ingestion/dedup.py`

Two module constants:

```python
_SOURCE_PRIORITY = {"theater_hamburg": 10, "hamburg_scraper": 0, "ticketmaster": 0}
_TIME_TOLERANCE_MINUTES = 60
_TITLE_JACCARD_MIN = 0.5
```

### Venue normalisation

```python
def _normalize_venue(name: str | None) -> str:
    """Casefold, strip parenthesized hall suffix, split CamelCase, collapse whitespace."""
```

- Strip trailing `\s*\([^)]*\)\s*$` (e.g. `"Laeiszhalle (Großer Saal)"` → `"Laeiszhalle"`).
- Insert space before uppercase runs (e.g. `"DeutschesSchauSpielHausHamburg"` → `"Deutsches Schau Spiel Haus Hamburg"`).
- Lower + normalise whitespace runs to single spaces + strip.
- Empty / None → `""`.

### Title Jaccard

```python
def _title_jaccard(a: str | None, b: str | None) -> float:
    """Token-set Jaccard on lower-cased, punctuation-stripped titles."""
```

- Strip punctuation via `re.sub(r"[^\w\s]", " ", ...)`, lower, split into token set.
- `|A ∩ B| / |A ∪ B|`; empty union → `0.0`.

### Grouping algorithm

```python
def dedup_events(session: Session) -> DedupReport
```

1. `SELECT id, source, venue_name, start_datetime, title, created_at FROM events WHERE is_active = True`.
2. Bucket by `(normalized_venue, floor(start_datetime → 60-min bucket))` — coarse pre-filter; a bucket may still hold non-matches.
3. Within each bucket, compute pairwise: two events match iff normalized venue equal (already true by bucket) AND `abs(dt_a - dt_b) <= 60min` AND `_title_jaccard(title_a, title_b) >= 0.5`. Union-find over matches → clusters.
4. For each cluster with `size > 1`:
   - Winner = `max(cluster, key=lambda e: (_SOURCE_PRIORITY.get(e.source, 0), -e.created_at.timestamp()))` — higher priority wins; on ties the older row wins (stability).
   - For each loser: `UPDATE saved_events SET event_id = winner.id WHERE event_id = loser.id`, then `DELETE FROM events WHERE id = loser.id`.
5. Report `{groups_found: int, rows_merged: int, saved_events_migrated: int}`.

**Transaction boundary:** one transaction for the whole `dedup_events` call. Ingestion adapters commit before this runs; dedup either fully succeeds or rolls back.

**Idempotence:** second run finds no cross-source clusters because all losers were deleted in the first run. Verified by test.

**Safety net for buckets that miss the edge:** because start_datetime bucketing is 60-min-floored, an event at 20:59 and one at 21:00 land in different buckets. Fix: compute matches across neighbouring buckets too (check `bucket` and `bucket + 1`). Adds constant factor but keeps correctness for the tolerance window.

---

## Part C — Scheduler wiring

`backend/app/ingestion/scheduler.py`:

- Add `TheaterHamburgAdapter` to `_default_adapters()`. If a shared `httpx.Client` needs to be plumbed for the wiki fallback, follow the existing pattern (already committed).
- At the end of `run_ingestion`, after the last adapter finishes and before the embedding step: call `dedup_events(session)` and log the report. Any exception in dedup fails the run loudly (nightly cron will retry).
- Order: adapters → dedup → embeddings. Embeddings already pick up only visible events; the dedup deletes losers, so their vectors get swept by the existing stale-sweep on the next embed run.

---

## Part D — Testing

### Unit tests

**`test_theater_hamburg.py`** — new:

- `test_list_paginates_until_last_page` — fake GraphQL client returning 2 pages; assert both consumed.
- `test_event_dates_are_expanded_to_separate_events` — one show with 3 upcoming dates → 3 `NormalizedEvent`s.
- `test_description_from_short_description_is_html_stripped`.
- `test_missing_description_skips_detail_call_and_leaves_none` — detail returns empty node (defensive).
- `test_detail_calls_are_cached_per_permalink` — 3 events sharing a slug → 1 detail call.
- `test_jwt_is_scraped_from_widget_js_on_init` — regex extraction against a fixture widget.js.
- `test_jwt_env_override_skips_scrape` — `THEATER_HAMBURG_JWT` set → no widget.js fetch.
- `test_401_triggers_one_rescrape_and_retry`.
- `test_malformed_node_is_skipped_not_fatal`.

**`test_dedup.py`** — new:

- `test_no_events_no_ops`.
- `test_theater_hamburg_wins_over_ticketmaster_same_venue_time_title` — TM row deleted, TH row survives.
- `test_venue_normalization_matches_across_camelcase_and_paren_suffix`.
- `test_title_jaccard_below_threshold_prevents_dedup_at_multi_screen_venue` — two events at "CinemaxX Dammtor" at 20:00 with disjoint titles → both kept.
- `test_time_tolerance_matches_across_bucket_boundaries` — 20:59 vs 21:00 with matching venue+title → deduped.
- `test_saved_events_fk_migrated_before_delete`.
- `test_idempotent_second_run_no_ops`.
- `test_ties_by_priority_broken_by_older_created_at`.

### Integration tests

**`test_scheduler.py`** — extend:

- `test_run_ingestion_calls_dedup_after_adapters` — order verified via monkey-patched sentinels.
- `test_dedup_failure_is_logged_and_raises` — dedup raises → run_ingestion propagates (no silent swallow).

### Fixtures

- `theater_hamburg_widget_sample.js` — real (trimmed) widget.js excerpt containing a JWT-shaped token.
- `theater_hamburg_search_sample.json` — real 2-event response captured in Task 0.
- `theater_hamburg_details_sample.json` — real detail response with HTML `shortDescription`.

Captured live during the plan's Task 0 (recon-preserve step); real strings are the only reliable way to validate parsing.

---

## File Map

| Action | File |
|---|---|
| Create | `backend/app/ingestion/scrapers/theater_hamburg.py` |
| Create | `backend/app/ingestion/dedup.py` |
| Modify | `backend/app/ingestion/scheduler.py` |
| Create | `backend/tests/ingestion/test_theater_hamburg.py` |
| Create | `backend/tests/ingestion/test_dedup.py` |
| Modify | `backend/tests/ingestion/test_scheduler.py` |
| Create | `backend/tests/fixtures/theater_hamburg_widget_sample.js` |
| Create | `backend/tests/fixtures/theater_hamburg_search_sample.json` |
| Create | `backend/tests/fixtures/theater_hamburg_details_sample.json` |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| JWT rotates or widget.js URL moves | Re-scrape on 401 (one retry); `THEATER_HAMBURG_JWT` env var override; loud failure on second 401 |
| GraphQL schema changes | Small, explicit field list per query — schema drift shows up as `KeyError` on parse, logged & skipped per event, not fatal |
| Venue normalisation misses a case (e.g. "Elphi" vs "Elbphilharmonie") | Titel-Jaccard safety net + explicit unit tests over observed venue name shapes; further normalisations added as concrete cases surface |
| False dedup at multi-screen venues (CinemaxX etc.) | Title-Jaccard ≥ 0.5 required — different films have disjoint token sets |
| Bucketing misses cross-hour matches | Compare against `bucket` and `bucket + 1` |
| Saved event silently deleted | FK migration `UPDATE saved_events SET event_id = winner.id` runs before every `DELETE`; test covers this explicitly |
| Rate limit / ban | 200 ms between detail calls; single UA; failure returns `None` per event, not aborting the run |
| Chroma vectors for deleted losers | Existing stale-sweep in `embed_new_events` removes any vector whose event id is no longer in the visible-filter set |

## Success Criteria

- After a full ingest: theater-hamburg contributes ~1500–2000 rows to `events`, all with non-empty `description`.
- Cross-source dedup drops ~10–30 collision groups (rough estimate — TM's high-profile Elphi/Laeiszhalle overlap).
- `saved_events` count is preserved across a dedup run (verified by test).
- Second dedup run in same session performs zero writes (idempotence, verified by test).
- All new + existing tests pass.
- Manual DB spot-check after one production ingest confirms `SELECT source, COUNT(*), SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) FROM events GROUP BY source` shows theater-hamburg at 100 % description coverage.
