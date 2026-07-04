# LLM-based Event Categorization

**Status:** Draft
**Date:** 2026-07-04
**Author:** brainstormed with Claude

## Problem

Event categories are currently assigned per-source at ingestion time via hard-coded
lookup tables (substring match for `theater_hamburg`, exact-match for `hamburg_scraper`,
`segment/genre` map for `ticketmaster`, `category` map for `eventbrite`).

The substring match in `TheaterHamburgAdapter._map_category`
(`backend/app/ingestion/scrapers/theater_hamburg.py:114-122`) is unreliable. Concrete
example:

- **The 27 Club** (31 shows, 2026-07-04 to 2026-08-01, St. Pauli Theater) is a jukebox
  musical / tribute show. Provider-tag is `"weitere konzerte"`. Substring-match hits
  `konzert` → `music`. Correct label is `theater` (venue and multi-week run pattern
  make this unambiguous).

Investigation showed the same failure mode across ~15% of `theater_hamburg` events
classified as `music` (e.g. *De Ohnsorg Süsters* in Ohnsorg-Theater, *Neo - Mannsvibe*
in Centralkomitee — both tagged `"weitere konzerte"`, both actually theater).

`theater_hamburg` accounts for **95% of ingested events** (6241/6592 rows). The
remaining sources (`ticketmaster`, `hamburg_scraper`) are small and their existing
mappings work acceptably, but for uniformity all sources will use the same
classification path.

## Non-goals

- Adding new event categories to the enum. Sticking with the ten defined in
  `EVENT_CATEGORIES` (`backend/app/schemas/common.py:6`).
- Venue-based deterministic mapping. Rejected during brainstorm because major venues
  (Elbphilharmonie, Laeiszhalle) host both concerts and non-concert events; a
  hard-coded venue table would be wrong for the ~20% edge cases with no signal to
  detect the error.
- Re-classifying events on every ingestion run. Each unique event content is classified
  **once**; a cache keyed on the content hash makes repeat fetches free.
- Multi-source deduplication changes (dedup runs after upsert, unaffected).

## Design

### High-level flow

```
adapter.fetch()
    → NormalizedEvent (with substring-mapped category as a hint)
    → categorize.refine(event, cache, llm_client)   ← NEW
        → cache lookup by content hash
        → on miss: call LLM with structured output
        → returns final EventCategory
    → upsert_events()
    → dedup_events()
    → embed_new_events()
```

Classification runs for **all events from all sources**. The category the scraper
computes today is passed to the LLM as a **hint**, not as authority.

### New module: `backend/app/ingestion/categorize.py`

Single public function:

```python
def refine_category(
    event: NormalizedEvent,
    cache: CategoryCache,
    llm_client: LLMClient,
) -> EventCategory:
    """Return the LLM-decided category. Falls back to event.category on failure."""
```

Content-hash calculation:

```python
def content_hash(event: NormalizedEvent) -> str:
    parts = [
        event.title or "",
        _strip_html(event.description or ""),
        event.venue_name or "",
        "|".join(sorted(event.tags)),
        event.category,  # provider hint is part of the identity
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
```

Note: the hash intentionally excludes `start_datetime`, `price_*`, `image_url`,
`source_url`, `external_id` — those change without affecting classification.

### Cache: new table `event_category_cache`

```sql
CREATE TABLE event_category_cache (
    content_hash TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    model        TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- `content_hash` from `content_hash(event)` above.
- `category` is one of `EVENT_CATEGORIES` **or the literal `"unknown"`** (the
  cached "model was unsure" signal — see error handling below).
- `model` is stored so a future model change can be handled as invalidation
  (delete-where-model-old, not part of MVP).
- No TTL. Rows are cheap; stale rows are harmless (they can only match if the exact
  same content reappears).

Read path: `SELECT category FROM event_category_cache WHERE content_hash = ?`.
Write path: `INSERT OR IGNORE INTO event_category_cache (...) VALUES (...)`.

### LLM call

Reuses `agent.llm.build_llm` pattern (OpenRouter via `langchain_openai.ChatOpenAI`).

- Model: `settings.categorization_model` (default `"google/gemini-2.0-flash"`).
- `temperature=0`, `max_retries=2`, `timeout=settings.categorization_timeout_seconds`
  (default `10.0`).
- Structured output via `.with_structured_output(CategoryDecision)` where
  `CategoryDecision` is a Pydantic model:

  ```python
  class CategoryDecision(BaseModel):
      category: EventCategory | Literal["unknown"]
  ```

  `"unknown"` is the "model is unsure" signal. `refine_category` writes `unknown`
  into the cache (so we don't call the LLM again for the same content) but returns
  `event.category` to the caller — the pipeline never sees `unknown` in
  `NormalizedEvent.category`, only in the cache table.

### Prompt

New file `backend/app/ingestion/categorize_prompts.py` holds the system prompt
constant and the `render_user_prompt(event)` helper. Separate file (not
`agent/prompts.py`) because the categorization prompt has a different lifecycle
and audience than the agent prompts.

System prompt: German + English category definitions with disambiguating hints
that reflect our observed failure modes. In particular:

- `theater` explicitly covers musical / tribute shows / Kabarett when they play as
  multi-week runs in a theater venue.
- `music` covers concerts, DJ-Sets, classical performances in concert halls.
- `arts` covers exhibitions, ballet, contemporary dance, readings.
- Unsure → `unknown`.

User prompt (filled per event):

```
Title: {title}
Description: {description_first_400_chars}
Venue: {venue_name}
Provider tags: {tags}
Source's suggested category: {event.category}
Source: {event.source}
```

### Configuration additions (`backend/app/config.py`)

```python
categorization_model: str = "google/gemini-2.0-flash"
categorization_timeout_seconds: float = 10.0
```

No kill-switch flag (YAGNI — if OpenRouter is down, ingestion has other problems).

### Pipeline integration (`backend/app/ingestion/scheduler.py`)

`run_ingestion` gains one step between `adapter.fetch()` and `upsert_events()`:

```python
cache = CategoryCache(session)
llm = build_categorization_llm()
for adapter in adapters:
    for ev in adapter.fetch():
        ev.category = refine_category(ev, cache, llm)
        all_events.append(ev)
```

`CategoryCache` uses the same SQLAlchemy session as everything else — no separate
connection pool.

### Error handling

| Failure                              | Behavior                                                                 |
| ------------------------------------ | ------------------------------------------------------------------------ |
| LLM timeout / network / 5xx          | Log warning, return `event.category`. **No cache write.** Retry next run. |
| LLM returns non-enum value           | Treat as `unknown` case. No cache write.                                 |
| LLM returns `"unknown"`              | Return `event.category`. Cache-write stores `unknown` (so we don't re-ask). |
| OpenRouter rate limit                | LangChain `max_retries=2` handles it; on exhaustion → same as timeout.   |
| Backfill migration killed mid-run    | Idempotent (INSERT OR IGNORE); rerun picks up where it stopped.          |

### Initial backfill (Alembic migration)

New Alembic migration `NNNN_add_event_category_cache.py`:

1. Creates `event_category_cache` table (schema step, fast).
2. Data step: iterates existing `events`, calls `refine_category` for each, updates
   `events.category` with the result. Runs at deployment time; takes ~15 minutes
   for the current 6241 rows.
3. Deactivated events are still classified (they may become active again if the
   provider re-lists them; classifying now avoids a stampede later).

If the operator prefers to defer the backfill, the migration can be split (schema
now, data script later). Baseline is: single migration, one deploy step.

## Testing strategy

**Unit tests** — `backend/tests/ingestion/test_categorize.py`:

- Cache hit: same content hash twice → single LLM call.
- Cache miss then hit: fresh content → LLM called → second call for same content
  hits cache.
- LLM error → returns `event.category`, no cache write.
- LLM returns `unknown` → returns `event.category`, cache write.
- LLM returns invalid enum value → same as error.

**Prompt snapshot** — `backend/tests/ingestion/test_categorize_prompt.py`:

- One golden fixture per representative event: `The 27 Club`, `Ohnsorg-Süsters`,
  a Ticketmaster music event, a Ticketmaster theater event. Snapshot the rendered
  prompt string so changes are visible in review.

**Existing tests** — `test_theater_hamburg.py`, `test_scheduler.py`:

- Get a `categorize_llm` parameter of type `LLMClient` protocol; pass in a
  `FakeCategorizationClient` that returns a fixed mapping `{title_substring: category}`.
- Tests never hit the real OpenRouter endpoint.

No real LLM calls in CI. Fake client covers the deterministic surface; the actual
model quality is verified manually via a `python -m app.ingestion.reclassify --sample 50`
CLI (see below).

## Operational commands

- `python -m app.ingestion.reclassify --all` — force re-classify every event
  (ignores cache; useful after prompt/model change).
- `python -m app.ingestion.reclassify --sample 50` — classify 50 random events with
  cache disabled, print a table for eyeballing. Used to validate prompt changes.
- Standard `alembic upgrade head` triggers the initial backfill migration.

## Cost estimate

Per current volume, using `google/gemini-2.0-flash`:

- Initial backfill: 6241 events × ~700 input tokens × $0.075/M = **~$0.33 one-time**.
- Ongoing: ~50-200 new/changed events per day × ~700 tokens = **~$0.40/year**.

Migration wall-clock: ~15 min at 5-10 requests/sec (single-threaded, with retries).

## Open items

- Concurrent classification during backfill (asyncio + `asyncio.Semaphore`) could
  cut the migration time to ~2 min. Deferred — 15 min is acceptable and simpler.
- Human-in-the-loop review UI for uncertain (`unknown`) classifications. Not in
  scope for MVP.
- Multi-model consensus (send to two cheap models, disagree = escalate). Not in
  scope; not justified by observed failure rate.
