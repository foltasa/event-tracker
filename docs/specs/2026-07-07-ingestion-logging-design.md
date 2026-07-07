# Ingestion Pipeline Logging — Design

**Date:** 2026-07-07
**Status:** Proposed

## Problem

The ingestion pipeline was wired together across multiple sessions with different agents per source. The result: inconsistent log output. `scheduler.py` emits reasonable `stage:` and `[adapter]` lines, but inside adapters the levels of detail vary wildly:

- `ohschonhell` narrates sitemap sizes, delta cutoffs, and every bad URL.
- `theater_hamburg`, `hamburg`, `eventbrite` log almost nothing except failures.
- `eventim` emits only warnings — no progress signal.
- `ticketmaster` logs enrichment failures but nothing about pagination progress.

The observable symptoms:

1. Cannot tell *why* a run is taking so long — silent for minutes, then a summary.
2. Cannot compare adapters at a glance — every one uses a different vocabulary.
3. Cannot see what post-fetch stages (`categorize`, `dedup`, `embed`) are doing internally, only that they finished.
4. Warnings mix operational red flags (Eventim anti-bot) with per-item parse failures — impossible to spot the important one in the noise.

## Goal

A consistent, high-but-not-overwhelming log stream that answers, at a glance:

- What stage of the run are we in, and how long has it been running?
- Which adapter is currently working, and is it making progress?
- How many events did each adapter contribute, and did anything fail?
- What did the post-fetch stages actually do (cache hit rate, dedup merges, embeddings changed)?

Non-goals (deferred, not blocked):

- Structured JSON output for aggregation tools (Loki, ES).
- Log rotation, per-run file sinks.
- Runtime-configurable verbosity knobs per adapter.

## Design

### Log format

Single fixed line format, human-readable, terminal-first, aligned columns:

```
2026-07-07 04:00:01 INFO  run.start           run=a3f2 sources=5
2026-07-07 04:00:01 INFO  fetch.start         [ticketmaster]
2026-07-07 04:00:31 INFO  fetch.progress      [ticketmaster] page=8 events=460 elapsed=30.1s
2026-07-07 04:00:34 WARN  fetch.warn          [ticketmaster] cat=wiki_fetch first="Bad Bunny"
2026-07-07 04:00:35 INFO  fetch.done          [ticketmaster] events=612 pages=11 warnings={wiki_fetch:8} elapsed=33.4s
2026-07-07 04:00:35 WARN  fetch.skipped       [eventim] reason=breaker-tripped since=2026-07-05
2026-07-07 04:01:02 INFO  stage.categorize    events=1204 cache_hits=1189 llm_calls=15 elapsed=12.8s
2026-07-07 04:01:03 INFO  stage.upsert        inserted=42 updated=1160 skipped=2 elapsed=0.5s
2026-07-07 04:01:04 INFO  stage.dedup         groups=8 merged=11 elapsed=0.9s
2026-07-07 04:01:09 INFO  stage.embed         upserted=1198 purged=6 elapsed=5.2s
2026-07-07 04:01:09 INFO  run.done            events=1198 elapsed=68.1s
```

Column widths:

- Timestamp: 19 chars (`YYYY-MM-DD HH:MM:SS`).
- Level: 5 chars, left-padded (`INFO `, `WARN `, `ERROR`, `DEBUG`).
- Event name: 20 chars, left-padded (dot-separated, e.g. `fetch.progress`).
- Body: `key=value` pairs, whitespace-separated. Multi-value counters render as `{key:val, key:val}`.

Adapter tag `[name]` is the first body token when the event is adapter-scoped. `run_id` is a 4-char hex tag, emitted only on `run.start` and `run.done` to keep other lines short. If a run fails, the surviving lines can be correlated by timestamp; runs never overlap.

### Event vocabulary

Anything not in this table gets logged at DEBUG (silent by default). This is the "high but not overwhelming" cap.

| Event | Emitted by | Body |
|---|---|---|
| `run.start` | scheduler | `run=<hex4>` `sources=<n>` |
| `run.done` | scheduler | `events=<n>` `elapsed=<Ns>` |
| `run.failed` | scheduler | `stage=<name>` `err="<type>"` `elapsed=<Ns>` |
| `fetch.start` | scheduler (per adapter) | `[adapter]` |
| `fetch.progress` | adapter via `ProgressReporter` | `[adapter]` `<counters>` `elapsed=<Ns>` |
| `fetch.warn` | adapter via `WarningCollector` | `[adapter]` `cat=<slug>` `first="<detail>"` |
| `fetch.op` | adapter via `WarningCollector.op` | `[adapter]` `<free-form key=val>` (Eventim-style operational warnings) |
| `fetch.done` | scheduler after adapter returns | `[adapter]` `events=<n>` `<counters>` `warnings={cat:n,…}` `elapsed=<Ns>` |
| `fetch.skipped` | scheduler | `[adapter]` `reason=<slug>` `[since=<date>]` |
| `fetch.failed` | scheduler | `[adapter]` `err="<type>"` `elapsed=<Ns>` |
| `stage.categorize` | scheduler | `events=<n>` `cache_hits=<n>` `llm_calls=<n>` `elapsed=<Ns>` |
| `stage.upsert` | scheduler | `inserted=<n>` `updated=<n>` `skipped=<n>` `elapsed=<Ns>` |
| `stage.dedup` | scheduler | `groups=<n>` `merged=<n>` `elapsed=<Ns>` |
| `stage.embed` | scheduler | `upserted=<n>` `purged=<n>` `elapsed=<Ns>` |

### Warning classification

Warnings split into two classes:

**Aggregated warnings** (`warns.warn(cat, detail)`): per-item parse or enrichment failures. Categories are short slugs picked per adapter (`wiki_fetch`, `detail_fetch`, `parse_error`, `bad_date`). The **first** occurrence per category emits `fetch.warn` at WARN with the detail; subsequent occurrences emit at DEBUG (silent by default) and are counted. Totals are folded into the `warnings={…}` field on `fetch.done`.

**Operational warnings** (`warns.op(msg, **fields)`): always emit `fetch.op` at WARN, never suppressed, never counted in the summary. Reserved for signals that indicate the adapter itself is at risk (anti-bot pressure, breaker preconditions, protocol degradation). Adapters decide which of their warnings are operational — only the adapter author knows what's a red flag.

Eventim-specific mapping (per CLAUDE.md guidance on anti-bot exposure):

- Unexpected HTTP status → `op`.
- 403 with anti-bot signature → `op`.
- Consecutive-failure counter tripping toward breaker → `op`.
- All-categories-empty condition → `op`.
- 403 budget exceeded → `op`.
- Circuit-breaker mid-run trip / disabled banner → `op`.

All other adapters use `warn` for per-item failures unless the adapter author explicitly promotes a category to `op`.

### Shared helpers

New module `backend/app/ingestion/logging_util.py`:

```python
class ProgressReporter:
    """Emits fetch.progress at most once every `interval_s` seconds.
    Adapters call tick(**counters) freely; the reporter throttles emissions.
    done() returns the final counters + elapsed for the scheduler to fold
    into fetch.done."""

    def __init__(self, adapter: str, interval_s: float = 30.0, clock=time.monotonic): ...
    def tick(self, **counters: int) -> None: ...   # cumulative, not deltas
    def done(self) -> dict: ...                    # {counter: value, elapsed_s: float}


class WarningCollector:
    """First warning per cat emits fetch.warn at WARN with detail.
    Subsequent occurrences emit at DEBUG (silent by default) and are counted.
    op() is a separate channel: always WARN, never counted, for operational
    warnings that must not be suppressed."""

    def __init__(self, adapter: str): ...
    def warn(self, cat: str, detail: str, exc: Exception | None = None) -> None: ...
    def op(self, msg: str, **fields) -> None: ...
    def summary(self) -> dict[str, int]: ...


@dataclass
class FetchContext:
    """Handed to SourceAdapter.fetch by the scheduler. Adapters use the
    helpers on this object rather than constructing their own so the
    scheduler always has full counters at fetch.done time."""
    progress: ProgressReporter
    warns: WarningCollector


@contextmanager
def timer(event: str, logger: logging.Logger, **body):
    """Times a block and emits `event` on exit with elapsed folded in.
    Body dict is evaluated at exit — pass a mutable dict and mutate it
    inside the block to accumulate counters (e.g. cache_hits, llm_calls)."""


def configure_logging(level: int = logging.INFO) -> None:
    """Install IngestionFormatter on the root logger. Called once from
    main.py (app) and scripts/ingest.py (CLI)."""


# No-op fallbacks so adapters can be called with ctx=None (tests, direct
# CLI use). Same interface as the real helpers; all methods do nothing.
class _NullProgress: ...
class _NullWarns: ...


class IngestionFormatter(logging.Formatter):
    """Produces the fixed column format. Reads event name and body from
    LogRecord.extras (event=..., body={...})."""
```

Adapter usage:

```python
def fetch(self, session, ctx: FetchContext | None = None):
    progress = ctx.progress if ctx else _NullProgress()
    warns = ctx.warns if ctx else _NullWarns()

    events = 0
    for page_num, page in enumerate(self._paginate(), start=1):
        for raw in page:
            try:
                ev = parse_event(raw)
            except Exception as e:
                warns.warn("parse_error", raw.get("id", "<no-id>"), exc=e)
                continue
            events += 1
            yield ev
        progress.tick(page=page_num, events=events)
```

### Adapter contract change

`SourceAdapter.fetch(session)` gains an optional `ctx: FetchContext | None = None` parameter (default `None` so existing tests pass unmodified). Scheduler owns `FetchContext` lifecycle: constructs one per adapter, passes it in, reads `progress.done()` and `warns.summary()` after the generator finishes, and folds them into the `fetch.done` line.

### Post-fetch stage instrumentation

- `CategoryCache` grows a `.stats` dict with `hits: int`; `LangchainClassifier` grows `.stats` with `calls: int`. Scheduler creates them, passes into `refine_category` as today, reads stats after the loop.
- `upsert_events` return value (`UpsertReport`) already carries the counters — no change needed there.
- `dedup_events` already logs a summary internally; refactor to accept a target logger and emit `stage.dedup` in the shared format instead of its own line.
- `embed_new_events` refactored to emit `stage.embed` in the shared format; drops its two ad-hoc info lines.
- Each stage wrapped in `timer("stage.X", …)` for the `elapsed=` field.

### Migration order

1. `logging_util.py` + unit tests.
2. `main.py` and `scripts/ingest.py` — call `configure_logging()`.
3. `base.py` — extend `SourceAdapter.fetch` signature with optional `ctx`.
4. `scheduler.py` — own `FetchContext` per adapter; emit new `run.*`, `fetch.*`, `stage.*` events; delete ad-hoc `[adapter]` lines superseded by the vocabulary.
5. `categorize.py` — add `.stats` to `CategoryCache` and `LangchainClassifier`.
6. Adapters, one at a time (small edits per file):
   - `ticketmaster.py` — page counter; `wiki_fetch`/`detail_fetch` as `warn`.
   - `scrapers/hamburg.py` — item counter; `detail_fetch`/`parse_error` as `warn`.
   - `scrapers/ohschonhell.py` — collapse existing info/warn calls into `progress.tick` + `warns.warn`.
   - `scrapers/theater_hamburg.py` — item counter; `parse_error` as `warn`; keep `401 → re-scrape JWT` as `op`.
   - `eventim.py` — item counter; all existing `logger.warning` calls become `warns.op(...)`.
   - `eventbrite.py` — page/item counter + `parse_error` as `warn`.
7. Post-fetch stage refactors (`normalize.py`, `dedup.py`) to emit shared-format lines.

## Testing

- `IngestionFormatter` — assert exact string output for a known LogRecord (fixed columns).
- `ProgressReporter` — fake clock; assert emits at 30s / 60s / … only, not in between.
- `WarningCollector` — first-per-cat at WARN with detail, rest at DEBUG, `summary()` shape, `op()` bypasses aggregation.
- Scheduler test with 2 fake adapters: assert the full expected log-line sequence (`run.start`, `fetch.start` × 2, `stage.*` × 4, `run.done`). This is the "did I break the vocabulary" guardrail.
- Existing adapter tests continue to pass with `ctx=None`.

## Anti-goals

- **No JSON output.** Terminal-first only. If external aggregation becomes a need, `configure_logging()` gains a JSON handler; the schema above already fits `key=val` naturally.
- **No per-adapter verbosity config.** One knob (`--log-level`) governs the whole run. Anything more granular is scope creep.
- **No log rotation, no file sink.** Cron output landing is out of scope for this design.
- **No changes to per-item DEBUG behavior beyond the aggregate-warning rule.** Adapters may still emit their own DEBUG lines however they like; DEBUG is off by default.

## Open questions

None.
