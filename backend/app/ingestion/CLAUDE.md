# Ingestion Pipeline — Design Notes for Future Agents

Read this before touching anything under `app/ingestion/`. It captures the invariants and design choices that are *not* obvious from the code.

## Purpose

Pull events from several external sources, normalize them into one canonical shape, classify them, deduplicate across sources, persist them, and make them searchable. All in one nightly cron. That's it — no live/on-demand fetches from user actions.

## Data flow

```
adapter.fetch()  →  NormalizedEvent  →  refine_category  →  upsert_events
                                                                 ↓
                                                         deactivate_past_events
                                                                 ↓
                                                            dedup_events
                                                                 ↓
                                                          embed_new_events
                                                                 ↓
                                                             session.commit
```

One transaction wraps the whole run (`run_ingestion` in `scheduler.py`). Adapters and the stage functions **never call `session.commit()` themselves** — the caller owns transaction boundaries. If a stage raises, the whole run rolls back.

Fetch failures on a single adapter are logged and skipped so one flaky source doesn't kill the run.

## Adapters

### Two module layouts, one contract

- **API adapters** live at `app/ingestion/*.py` — `ticketmaster.py`, `eventbrite.py`, and future `eventim.py`.
- **HTML-scraping adapters** live at `app/ingestion/scrapers/*.py` — `hamburg.py`, `ohschonhell.py`, `theater_hamburg.py` (the last is GraphQL but its whole raison d'être is extracting a JWT from a widget page, so it belongs with the scrapers).

Class naming follows the split: `*Adapter` for API-based, `*Scraper` for HTML-parsing. Contract is the same: `SourceAdapter` Protocol in `base.py` — a `name: str` and `fetch(session) -> Iterator[NormalizedEvent]`.

### Adapter responsibilities and boundaries

- **Only** produce `NormalizedEvent`s. Don't touch the `Event` table, don't call `upsert_events`, don't run LLMs.
- Prefer streaming (`yield`) over building a full list — adapters can be long-running.
- Keep any HTML/JSON parsing behind a **pure function** (`parse_event`, `parse_product`, …) that takes bytes/dict and returns `dict` or `NormalizedEvent | None`. This is the unit-testable core; the adapter class is just paginator + HTTP + session I/O around it.
- Use `IngestionState` (see below) for delta cursors when a source supports it; leave it alone when it doesn't. A stateless full-crawl adapter is a valid choice when the source has no lastmod and upsert is cheap enough.

### Politeness and anti-bot

- Every adapter that hits an external service uses an honest `User-Agent` (`EventTrackerBot/1.0 (…)`). Impersonating a browser is only done where an edge fingerprints for one (currently: eventim's Akamai) — and only as far as headers, not JS execution.
- Modest inter-request delay (typically 150–300ms). No adapter runs concurrent requests today — the whole run is happy at ~2 minutes total.
- Sources that ban clients aggressively (Ticketmaster HTML, Eventim expected) should implement a **circuit breaker** on top of retries: after N sustained failures, persist a "disabled until manually reset" flag and refuse to hit the endpoint at all until an operator runs a reset script. Never auto-recover — auto-recovery invites a permanent ban.

## `NormalizedEvent` field semantics — the important ones

Full schema in `normalize.py`. What matters *conceptually*:

- **`external_id` + `source`** is the composite primary key for idempotence. Adapters must pick a stable per-event id from the source. Same event on two runs → same `external_id` → row is updated, not duplicated.
- **`description`** is the ONLY user-facing free-text field. It shows up in the frontend (`EventDetailOverlay`), in agent tool results, and as input to embeddings. Everything hangs off it.
- **`summary`** is dead plumbing. The DB column exists, but nothing reads it: no API, no frontend, no agent, no embedder. Don't invent uses for it — put user-facing text in `description`.
- **`description` empty ⇒ event hidden.** By default `visible_events_filter()` (in `app/db/models/event.py`) filters out any event with `description IS NULL OR description = ''`. This is applied at every user-facing query site (list, calendar, agent search, embeddings). An adapter that ships `description=None` is opting the event out of visibility. Operator can flip `HIDE_EVENTS_WITHOUT_DESCRIPTION=false` to unhide, but the default is on. Don't fake a description to avoid this filter — the filter's whole point is that visible = has a real description.
- **`category`** is a **hint**, not authority. The categorizer (see below) treats the adapter's category as one input among many and can override it. Adapters should pick the closest match from `EventCategory` based on whatever the source calls the event; `"other"` is a valid fallback for unknown types.
- **`tags`** is where you put the source's fine-grained genre/subcategory strings, artist names, and anything else the recommender might key on. No canonical vocabulary — it's a bag of strings.
- **`start_datetime`** must be timezone-aware (validator enforces). Assume `Europe/Berlin` for sources that ship naive datetimes and document that in the parser.
- **`raw_data`** is for debugging and reproducibility. Store source ids, sitemap `lastmod`, whatever helps you re-find the original record. Nothing in the runtime reads it — treat it as a diagnostic log line embedded in the row.

## Description enrichment — no LLM-generated descriptions

**LLM-generated descriptions are explicitly disallowed** — they could mislead users. When a source ships thin or missing descriptions, the pattern is to fall back to another **real, factual source**:

- Ticketmaster uses Wikipedia (via `attractions[].externalLinks.wiki`), fetched from `wikipedia.py`. See `docs/specs/2026-07-01-event-descriptions-fallback-design.md` Amendment 2 for the design.
- Everything without a real description gets hidden (see the `visible_events_filter` behavior above).

The LLM in this pipeline is used **only for categorization**, not for text generation. If a new source needs description enrichment, use a real reference source (Wikipedia, MusicBrainz, artist homepages) — never generate.

## Categorization — LLM as final authority, with a cache

`refine_category` in `categorize.py` runs between fetch and upsert. It calls a `LangchainClassifier` for each event, but is **cache-first**: the cache is keyed on a content hash over the event's semantic identity (title, description, venue, tags, adapter's category hint). Same-content events across runs pay $0 in LLM calls.

Key design choices:

- The adapter's `category` field is one input to the classifier's prompt, not the answer. If the adapter guesses "concerts" but the LLM decides "comedy", the LLM wins.
- Content hash excludes fields that change without affecting category (datetime, price, image url, source url). Same event re-fetched with a new image doesn't invalidate its classification.
- The classifier is optional in `run_ingestion` — tests can inject a fake `LLMClassifier`. Never call the classifier from inside an adapter's `fetch` (would defeat batching and cache tests).

## State cursor pattern

`IngestionState` (in `db/models/ingestion_state.py`) is a per-source cursor table. Two helpers in `state.py`:

- `get_last_seen(session, source) -> datetime | None` — call at the start of `fetch()` to get the delta cutoff. `None` means "first run — bootstrap".
- `set_last_seen(session, source, ts)` — call at the end of `fetch()` (before yielding stops) with the max lastmod actually processed. Never commit — caller owns the transaction.

Adapters decide the **semantics** of the timestamp. `ohschonhell` uses sitemap `lastmod`. Adapters that don't need a cursor simply don't touch the table. There's no ORM-level constraint that every source has a row.

The table is a natural home for per-source operational flags too — e.g. the Eventim circuit-breaker `disabled_at`/`disabled_reason` columns. Extend it rather than adding parallel per-source tables.

## Post-fetch stages you don't need to think about (usually)

- **`upsert_events`** — inserts new rows, updates existing rows by `(external_id, source)`. Idempotent. `raw_data` overwritten each run (fine — it's diagnostic).
- **`deactivate_past_events`** — flips `is_active=false` for events whose `start_datetime` is in the past. Adapters don't need to filter out past events themselves.
- **`dedup_events`** — cross-source dedup. Groups active events by `(normalized venue, ±60min start, title-Jaccard ≥ 0.5)`. Highest-`_SOURCE_PRIORITY` row wins, loser rows are deleted and any `SavedEvent` FKs migrated to the winner. If you add a source, decide its `_SOURCE_PRIORITY` value — default 0 is fine for new sources.
- **`embed_new_events`** — pushes visible events into Chroma and drops stale vectors. Reads `visible_events_filter()` so it stays consistent with the API/frontend.

## Anti-patterns — things not to do

- **Don't commit inside `fetch` or `parse`.** The caller owns the transaction. `state.set_last_seen` doesn't commit either.
- **Don't fetch HTTP inside `parse_*` pure functions.** Fetching goes in the adapter class; parsing is byte/dict-in, event-out. This is what keeps unit tests fast and hermetic.
- **Don't upsert or query `Event` from an adapter.** Adapters only touch `IngestionState` (and only through the helpers). Cross-source consistency is `dedup_events`' job.
- **Don't LLM-generate descriptions.** See above.
- **Don't fake a description just to bypass `visible_events_filter`.** If the source doesn't have real description content, let the event get hidden.
- **Don't add per-source visibility toggles.** If a source is producing garbage, fix the parser or the source config — don't add filtering downstream.
- **Don't skip the `refine_category` step for a new source** unless it can't fit in the current shape (talk to a human first).

## Testing conventions

- Every adapter has a fixture-based unit test for its `parse_*` function. Fixtures are minimal captures from live probes, hand-trimmed to preserve structure. Store under `backend/tests/ingestion/fixtures/<source>/`.
- Retry helpers get their own tests using a fake HTTP client (usually just a small class implementing `.get(url, **kwargs)` and returning canned `httpx.Response`-ish objects). No `httpx-mock` today — hand-rolled fakes are enough.
- Adapter-level tests inject the fake client via the constructor and a fake `sleep_fn` so retries don't actually sleep. Every adapter's `__init__` accepts these — keep that convention.
- Scheduler / stage tests use a real (in-memory SQLite) session and a fake `LLMClassifier`. Never make a real LLM call from a test.

## Read these when in doubt

- Adapter design examples: `scrapers/ohschonhell.py` (sitemap-delta, HTML microdata), `ticketmaster.py` (paginated API with Wikipedia fallback), `scrapers/theater_hamburg.py` (widget JWT extraction + GraphQL).
- Full spec index: `docs/specs/`. Recent decisions worth knowing: `2026-07-01-event-descriptions-fallback-design.md` (Amendment 2 = the "no LLM descriptions, use Wikipedia" pivot), `2026-07-04-llm-event-categorization-design.md` (categorizer contract), `2026-07-06-ohschonhell-scraper-design.md` (sitemap-delta pattern).
