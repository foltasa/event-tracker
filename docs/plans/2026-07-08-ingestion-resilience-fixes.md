# Ingestion Resilience Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three concrete issues surfaced by the first full ingestion run: (a) noisy third-party library logs drowning the ingestion vocabulary, (b) `UNIQUE (external_id, source)` IntegrityError crashing the whole run when an adapter yields duplicate events, (c) no end-of-run summary showing which adapters had a fetch failure.

**Architecture:** Three surgical, independent changes.
1. Silence known noisy library loggers (`httpx`, `httpcore`, `openai`, `urllib3`, `langchain*`, `apscheduler`) inside `configure_logging()`.
2. Add an in-memory batch-dedup step in the scheduler, keyed on `(source, external_id)`, that runs after the fetch loop and before categorize. Emit a new `stage.batch_dedup` log event when duplicates were dropped.
3. Track failed-fetch adapters during the run and, if any exist, print a highly-visible multi-line banner after `run.done` plus a `failed_adapters={...}` field on the `run.done` body itself.

None of these changes touch the transaction model (one commit at end of run) or the adapter contract.

**Tech Stack:** Python 3.11+, pytest, SQLAlchemy 2.x, standard library `logging`.

---

## File Structure

**Modify:**
- `backend/app/ingestion/logging_util.py` — add `_NOISY_LIBRARY_LOGGERS` constant and library-level silencing inside `configure_logging()`.
- `backend/app/ingestion/normalize.py` — add pure helper `dedup_by_external_id(events) -> tuple[list[NormalizedEvent], dict[str, int]]`.
- `backend/app/ingestion/scheduler.py` — wire batch dedup between fetch loop and categorize; track failed adapters; emit end-of-run banner.

**Modify (tests):**
- `backend/tests/ingestion/test_logging_util.py` — test noisy loggers get silenced.
- `backend/tests/ingestion/test_normalize.py` — test `dedup_by_external_id`.
- `backend/tests/ingestion/test_scheduler.py` — test end-of-run banner + duplicate collapse behaviour.
- `backend/tests/ingestion/test_scheduler_logging.py` — update the vocabulary guardrail to accept the new `stage.batch_dedup` event (conditional presence).

**No CLAUDE.md update needed.** The transaction model comment in `backend/app/ingestion/CLAUDE.md` remains accurate (one commit, one rollback).

---

## Task 1: Silence Noisy Third-Party Library Loggers

**Files:**
- Modify: `backend/app/ingestion/logging_util.py:83-98`
- Test: `backend/tests/ingestion/test_logging_util.py`

**Context:** After `configure_logging()` sets the root logger to INFO, third-party libraries (`httpx` in particular, called on every LLM classification via `langchain_openai`) emit INFO-level "HTTP Request: POST ... 200 OK" lines that propagate to the root handler and flood the terminal. We silence a fixed list of known-noisy libraries by pinning their loggers to WARNING.

- [ ] **Step 1.1: Write failing test for library silencing**

Add this test at the end of `backend/tests/ingestion/test_logging_util.py`:

```python
def test_configure_logging_silences_noisy_libraries():
    import io

    from app.ingestion.logging_util import configure_logging

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    noisy = ["httpx", "httpcore", "openai", "urllib3",
             "langchain", "langchain_core", "langchain_openai",
             "apscheduler"]
    saved_levels = {name: logging.getLogger(name).level for name in noisy}
    try:
        stream = io.StringIO()
        configure_logging(level=logging.INFO, stream=stream)
        for name in noisy:
            lvl = logging.getLogger(name).level
            assert lvl >= logging.WARNING, f"{name} at level {lvl}, expected WARNING+"
        # Sanity: root itself is still at the configured level.
        assert root.level == logging.INFO
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        for name, lvl in saved_levels.items():
            logging.getLogger(name).setLevel(lvl)
```

- [ ] **Step 1.2: Run test to verify it fails**

Run:
```
pytest backend/tests/ingestion/test_logging_util.py::test_configure_logging_silences_noisy_libraries -v
```

Expected: FAIL — the assertion `lvl >= WARNING` fails because loggers inherit from root INFO.

- [ ] **Step 1.3: Implement silencing in `configure_logging`**

Modify `backend/app/ingestion/logging_util.py`. Add a module-level constant just above `configure_logging()` (after the `_LEVEL_COL_WIDTH` constants near the top, so it's easy to spot):

```python
# Libraries that log at INFO on every network call and would otherwise
# drown the ingestion vocabulary. Silenced to WARNING by configure_logging.
_NOISY_LIBRARY_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "openai",
    "urllib3",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "apscheduler",
)
```

Then extend `configure_logging()` to pin those loggers. Replace the existing function body with:

```python
def configure_logging(level: int = logging.INFO, stream=None) -> None:
    """Install IngestionFormatter on the root logger.

    Idempotent: replaces any handlers previously installed by this function
    (marked with `_ingestion_managed`). Leaves foreign handlers alone so
    pytest capture and other stacks continue to work. Also pins known-noisy
    third-party loggers to WARNING so their per-request INFO lines don't
    flood the terminal (see _NOISY_LIBRARY_LOGGERS)."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [
        h for h in root.handlers
        if not getattr(h, "_ingestion_managed", False)
    ]
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(IngestionFormatter())
    handler._ingestion_managed = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    for name in _NOISY_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
```

- [ ] **Step 1.4: Run test to verify it passes**

Run:
```
pytest backend/tests/ingestion/test_logging_util.py -v
```

Expected: PASS. All existing tests plus the new one.

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): silence noisy library loggers in configure_logging"
```

---

## Task 2: In-Batch Dedup Helper `dedup_by_external_id`

**Files:**
- Modify: `backend/app/ingestion/normalize.py`
- Test: `backend/tests/ingestion/test_normalize.py`

**Context:** Adapters that iterate overlapping category endpoints (Eventim iterates four top-level categories that Eventim itself cross-tags) can yield the same `(source, external_id)` twice within one run. `SessionLocal` uses `autoflush=False`, so `upsert_events` doesn't see the earlier pending INSERT and enqueues a second one. The UNIQUE constraint blows up at the next `session.flush()` (currently the one inside `dedup_events`). We fix this at the ingestion boundary: dedup the batch in RAM before it reaches `upsert_events`.

The helper is a **pure function** — deterministic, no I/O, no logging — and returns both the deduplicated list AND a per-source drop-count dict so the scheduler can emit a useful log line.

- [ ] **Step 2.1: Write failing test — no duplicates case**

Open `backend/tests/ingestion/test_normalize.py`. Add these imports at the top if not present:

```python
from datetime import datetime, timezone
from app.ingestion.normalize import NormalizedEvent, dedup_by_external_id
```

Add a small helper at module scope (if a similar `_ev(...)` helper already exists in the file, reuse it — don't duplicate):

```python
def _norm(source: str, external_id: str, title: str = "T") -> NormalizedEvent:
    return NormalizedEvent(
        external_id=external_id,
        source=source,
        title=title,
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc),
        category="concerts",
        is_free=False,
        source_url=f"https://example.com/{source}/{external_id}",
    )
```

Then add:

```python
def test_dedup_by_external_id_passes_through_when_no_duplicates():
    events = [_norm("eventim", "1"), _norm("eventim", "2"), _norm("hamburg", "1")]
    result, drops = dedup_by_external_id(events)
    assert [(e.source, e.external_id) for e in result] == [
        ("eventim", "1"), ("eventim", "2"), ("hamburg", "1"),
    ]
    assert drops == {}
```

- [ ] **Step 2.2: Write failing test — duplicates case**

Add:

```python
def test_dedup_by_external_id_keeps_first_and_counts_drops_per_source():
    a = _norm("eventim", "1", title="Original")
    b = _norm("eventim", "1", title="Duplicate-later")
    c = _norm("eventim", "2")
    d = _norm("hamburg", "1")
    e = _norm("hamburg", "1")  # duplicate of d
    f = _norm("hamburg", "1")  # duplicate of d again
    result, drops = dedup_by_external_id([a, b, c, d, e, f])

    # First occurrence wins (a for eventim/1, d for hamburg/1).
    assert result == [a, c, d]
    # Drop counts per source; sources with zero drops omitted.
    assert drops == {"eventim": 1, "hamburg": 2}


def test_dedup_by_external_id_empty_input():
    result, drops = dedup_by_external_id([])
    assert result == []
    assert drops == {}
```

- [ ] **Step 2.3: Run tests to verify they fail**

Run:
```
pytest backend/tests/ingestion/test_normalize.py::test_dedup_by_external_id_passes_through_when_no_duplicates backend/tests/ingestion/test_normalize.py::test_dedup_by_external_id_keeps_first_and_counts_drops_per_source backend/tests/ingestion/test_normalize.py::test_dedup_by_external_id_empty_input -v
```

Expected: `ImportError: cannot import name 'dedup_by_external_id'` — the function doesn't exist yet.

- [ ] **Step 2.4: Implement `dedup_by_external_id`**

Modify `backend/app/ingestion/normalize.py`. Add this function just below `deactivate_past_events` at the bottom of the file:

```python
def dedup_by_external_id(
    events: Iterable[NormalizedEvent],
) -> tuple[list[NormalizedEvent], dict[str, int]]:
    """Collapse events sharing `(source, external_id)`; keep first occurrence.

    Some adapters (e.g. Eventim) iterate overlapping category endpoints and
    can yield the same product twice in one run. Since SessionLocal uses
    autoflush=False, upsert_events cannot see pending INSERTs during its own
    SELECTs and would enqueue a duplicate row -- blowing up UNIQUE
    (external_id, source) at the first flush downstream. Deduping at the
    ingestion boundary keeps upsert honest.

    Returns (kept_events, drops_by_source) where drops_by_source only lists
    sources that actually had drops. First occurrence is kept for stability
    and to align with the semantic that later occurrences don't carry new
    information."""
    seen: set[tuple[str, str]] = set()
    kept: list[NormalizedEvent] = []
    drops: dict[str, int] = {}
    for ev in events:
        key = (ev.source, ev.external_id)
        if key in seen:
            drops[ev.source] = drops.get(ev.source, 0) + 1
            continue
        seen.add(key)
        kept.append(ev)
    return kept, drops
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run:
```
pytest backend/tests/ingestion/test_normalize.py -v
```

Expected: PASS for all three new tests plus all existing normalize tests.

- [ ] **Step 2.6: Commit**

```bash
git add backend/app/ingestion/normalize.py backend/tests/ingestion/test_normalize.py
git commit -m "feat(ingestion): dedup_by_external_id helper for in-batch collapse"
```

---

## Task 3: Wire In-Batch Dedup Into Scheduler

**Files:**
- Modify: `backend/app/ingestion/scheduler.py:119-189`
- Test: `backend/tests/ingestion/test_scheduler.py`
- Test: `backend/tests/ingestion/test_scheduler_logging.py`

**Context:** After all adapters have run, we collapse `all_events` via `dedup_by_external_id`. If ANY drops happened, we log a new `stage.batch_dedup` event with the per-source drop counts so operators can spot adapter design flaws. If no drops, no log line — we don't add noise to healthy runs.

**Event vocabulary:** New event `stage.batch_dedup` with body `{"dropped": {source: count, ...}}`. Fires between the fetch loop and `stage.categorize`. This is distinct from the existing `stage.dedup` (cross-source dedup on venue+time+title in the DB); the naming reflects that.

- [ ] **Step 3.1: Write failing test — scheduler collapses duplicates and logs `stage.batch_dedup`**

Add to `backend/tests/ingestion/test_scheduler.py` (uses fixtures already defined in that file: `db_session`, `fake_classifier`, `_ev`):

```python
def test_scheduler_collapses_intra_batch_duplicates(db_session, fake_classifier, caplog):
    """Adapter yields the same (source, external_id) twice in one fetch.

    The scheduler must dedup in RAM before upsert so we don't crash the
    session with a UNIQUE (external_id, source) IntegrityError at flush."""
    import logging as _logging

    class _DupAdapter:
        name = "dup"

        def fetch(self, session, ctx=None):
            # Same external_id yielded twice: the adapter has an overlapping
            # category iteration bug (mimics real Eventim behaviour).
            yield NormalizedEvent(
                external_id="X", source="dup", title="First",
                start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
                category="concerts", is_free=False,
                source_url="https://example.com/dup/X",
            )
            yield NormalizedEvent(
                external_id="X", source="dup", title="Second-copy",
                start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
                category="concerts", is_free=False,
                source_url="https://example.com/dup/X",
            )

    caplog.set_level(_logging.INFO)
    report = run_ingestion(
        adapters=[_DupAdapter()], session=db_session, classifier=fake_classifier,
    )
    # Only ONE row inserted despite two yields.
    assert report.inserted == 1
    # First occurrence wins.
    stored = db_session.query(Event).filter_by(source="dup", external_id="X").one()
    assert stored.title == "First"
    # A stage.batch_dedup event was emitted with the drop count.
    dedup_events = [
        r for r in caplog.records
        if getattr(r, "event", None) == "stage.batch_dedup"
    ]
    assert len(dedup_events) == 1
    assert dedup_events[0].body == {"dropped": {"dup": 1}}


def test_scheduler_omits_batch_dedup_log_when_no_duplicates(db_session, fake_classifier, caplog):
    """When adapters are clean, no stage.batch_dedup line should appear."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier,
    )
    dedup_events = [
        r for r in caplog.records
        if getattr(r, "event", None) == "stage.batch_dedup"
    ]
    assert dedup_events == []
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run:
```
pytest backend/tests/ingestion/test_scheduler.py::test_scheduler_collapses_intra_batch_duplicates backend/tests/ingestion/test_scheduler.py::test_scheduler_omits_batch_dedup_log_when_no_duplicates -v
```

Expected: the first test fails with `IntegrityError` (or `report.inserted == 2`, depending on flush timing); the second passes vacuously. Both must be run — the first is the real regression test.

- [ ] **Step 3.3: Wire the dedup step into `run_ingestion`**

Modify `backend/app/ingestion/scheduler.py`. Update the import block near the top:

```python
from app.ingestion.normalize import (
    UpsertReport,
    deactivate_past_events,
    dedup_by_external_id,
    upsert_events,
)
```

Then, inside `run_ingestion`, find the block right after the fetch loop finishes and before `# --- Categorization ---` (currently around lines 179-181):

```python
            all_events.extend(batch)
            total_events += len(batch)

        # --- Categorization ---
```

Replace with:

```python
            all_events.extend(batch)
            total_events += len(batch)

        # --- In-batch dedup ---
        # Collapse (source, external_id) duplicates before they reach the
        # session. Without this, autoflush=False lets duplicate INSERTs
        # queue up and blow the UNIQUE constraint at the next flush.
        all_events, batch_drops = dedup_by_external_id(all_events)
        total_events = len(all_events)
        if batch_drops:
            logging.getLogger("app.ingestion.stage").info(
                "",
                extra={
                    "event": "stage.batch_dedup",
                    "body": {"dropped": batch_drops},
                },
            )

        # --- Categorization ---
```

Note: `total_events` gets recomputed so the final `run.done` reflects the count actually flowing downstream, not the raw sum-of-yields.

- [ ] **Step 3.4: Update the vocabulary guardrail test**

The vocabulary guardrail in `backend/tests/ingestion/test_scheduler_logging.py` uses fake adapters with unique external_ids, so it should NOT see `stage.batch_dedup`. But we want the test to keep passing AND to be robust if someone later adds a duplicate-yielding adapter to the guardrail. Filter `stage.batch_dedup` from the observed sequence the same way `fetch.progress` is filtered.

Change the filter set from:

```python
    seen = [
        e for e in events
        if e not in {"fetch.progress", "fetch.warn", "fetch.op"}
    ]
```

to:

```python
    seen = [
        e for e in events
        if e not in {"fetch.progress", "fetch.warn", "fetch.op", "stage.batch_dedup"}
    ]
```

- [ ] **Step 3.5: Run all three affected test files to verify pass**

Run:
```
pytest backend/tests/ingestion/test_scheduler.py backend/tests/ingestion/test_scheduler_logging.py backend/tests/ingestion/test_normalize.py -v
```

Expected: all PASS. Especially:
- `test_scheduler_collapses_intra_batch_duplicates` — was failing, now green.
- `test_scheduler_emits_full_vocabulary_in_order` — still green, unaffected by the filter change.

- [ ] **Step 3.6: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py backend/tests/ingestion/test_scheduler_logging.py
git commit -m "feat(ingestion): collapse (source,external_id) duplicates before upsert"
```

---

## Task 4: End-of-Run Banner for Failed Adapters

**Files:**
- Modify: `backend/app/ingestion/scheduler.py:126-166` (fetch loop) and around lines 216-224 (`run.done` emission)
- Test: `backend/tests/ingestion/test_scheduler.py`

**Context:** The scheduler already isolates per-adapter fetch failures (try/except in the loop → `fetch.failed` log + `continue`). But nothing surfaces at the *end* of the run to signal partial degradation. Operators reading logs have to grep for `fetch.failed` and count. We add:
1. A `failed_adapters: dict[str, str]` tracked in the loop, mapping `adapter.name → exception type name`.
2. A `failed_adapters={...}` field on the existing `run.done` log body (only when non-empty).
3. A multi-line ASCII banner logged AFTER `run.done`, styled like the existing Eventim circuit-breaker banner, only when `failed_adapters` is non-empty.

This is independent of the transactional model — no rollback semantics change. Adapters that failed to fetch already produce zero data; the banner just makes it visible.

- [ ] **Step 4.1: Write failing test — banner appears on partial failure**

Add to `backend/tests/ingestion/test_scheduler.py`. Note: use the existing `_OkAdapter` and `_FailAdapter` classes at the top of the file.

```python
def test_scheduler_end_of_run_banner_lists_failed_adapters(db_session, fake_classifier, caplog):
    """Partial failure: one adapter throws, others succeed.

    Post-run.done we expect:
      - `run.done` body carries `failed_adapters={fail: RuntimeError}`.
      - A multi-line WARNING banner is logged with the successful and
        failed adapter names, right after run.done."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter(), _FailAdapter()],
        session=db_session, classifier=fake_classifier,
    )

    # run.done carries the failure map.
    run_done = [r for r in caplog.records if getattr(r, "event", None) == "run.done"]
    assert len(run_done) == 1
    assert run_done[0].body.get("failed_adapters") == {"fail": "RuntimeError"}

    # Banner appears AFTER run.done in the record stream, at WARNING level.
    all_msgs = [r.getMessage() for r in caplog.records]
    banner_indices = [
        i for i, m in enumerate(all_msgs)
        if "INGESTION RUN COMPLETED WITH FAILURES" in m
    ]
    run_done_index = next(
        i for i, r in enumerate(caplog.records)
        if getattr(r, "event", None) == "run.done"
    )
    assert len(banner_indices) == 1, "expected exactly one banner"
    assert banner_indices[0] > run_done_index
    banner = all_msgs[banner_indices[0]]
    assert "Successful: ok" in banner
    assert "Failed:     fail (RuntimeError)" in banner
    # Banner logged at WARNING so it stands out.
    assert caplog.records[banner_indices[0]].levelno == _logging.WARNING


def test_scheduler_no_banner_when_all_adapters_succeed(db_session, fake_classifier, caplog):
    """Healthy run: no banner, no failed_adapters field on run.done."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier,
    )

    run_done = [r for r in caplog.records if getattr(r, "event", None) == "run.done"]
    assert len(run_done) == 1
    assert "failed_adapters" not in run_done[0].body

    all_msgs = [r.getMessage() for r in caplog.records]
    assert not any("INGESTION RUN COMPLETED WITH FAILURES" in m for m in all_msgs)
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run:
```
pytest backend/tests/ingestion/test_scheduler.py::test_scheduler_end_of_run_banner_lists_failed_adapters backend/tests/ingestion/test_scheduler.py::test_scheduler_no_banner_when_all_adapters_succeed -v
```

Expected: the first fails (no banner, `failed_adapters` missing on run.done); the second passes vacuously.

- [ ] **Step 4.3: Implement failure tracking and banner in `run_ingestion`**

Modify `backend/app/ingestion/scheduler.py`.

**Change A (initialize the tracker):** In `run_ingestion`, just after `total_events = 0` (currently line 119), add:

```python
    total_events = 0
    failed_adapters: dict[str, str] = {}
    current_stage = "fetch"
```

**Change B (record failures in the except block):** Find the fetch-failure except block (currently lines 154-166):

```python
            except Exception as exc:
                fetch_logger.exception(
                    "",
                    extra={
                        "event": "fetch.failed",
                        "body": {
                            "adapter": adapter.name,
                            "err": type(exc).__name__,
                            "elapsed_s": time.monotonic() - t0,
                        },
                    },
                )
                continue
```

Replace with:

```python
            except Exception as exc:
                failed_adapters[adapter.name] = type(exc).__name__
                fetch_logger.exception(
                    "",
                    extra={
                        "event": "fetch.failed",
                        "body": {
                            "adapter": adapter.name,
                            "err": type(exc).__name__,
                            "elapsed_s": time.monotonic() - t0,
                        },
                    },
                )
                continue
```

**Change C (extend `run.done` body + emit banner):** Find the current `run.done` emission (around lines 216-225):

```python
        run_logger.info(
            "",
            extra={
                "event": "run.done",
                "body": {
                    "events": total_events,
                    "elapsed_s": time.monotonic() - run_start,
                },
            },
        )
        return report
```

Replace with:

```python
        run_done_body: dict = {
            "events": total_events,
            "elapsed_s": time.monotonic() - run_start,
        }
        if failed_adapters:
            run_done_body["failed_adapters"] = failed_adapters
        run_logger.info("", extra={"event": "run.done", "body": run_done_body})

        if failed_adapters:
            successful = [
                a.name for a in adapters if a.name not in failed_adapters
            ]
            _emit_failure_banner(run_logger, successful, failed_adapters)

        return report
```

**Change D (define `_emit_failure_banner` helper):** Add this module-level function just above `create_scheduler()` (around line 249):

```python
def _emit_failure_banner(
    logger_: logging.Logger,
    successful: list[str],
    failed: dict[str, str],
) -> None:
    """Log a highly-visible multi-line banner listing successful and failed
    adapters. Mirrors the style of the Eventim circuit-breaker banner so
    operators recognize the shape immediately."""
    succ_str = ", ".join(successful) if successful else "(none)"
    fail_str = ", ".join(f"{name} ({err})" for name, err in failed.items())
    logger_.warning(
        "\n!! ============================================================\n"
        "!! INGESTION RUN COMPLETED WITH FAILURES\n"
        "!!   Successful: %s\n"
        "!!   Failed:     %s\n"
        "!!   Note: successful adapter data was persisted.\n"
        "!! ============================================================",
        succ_str, fail_str,
    )
```

- [ ] **Step 4.4: Run new tests to verify they pass**

Run:
```
pytest backend/tests/ingestion/test_scheduler.py::test_scheduler_end_of_run_banner_lists_failed_adapters backend/tests/ingestion/test_scheduler.py::test_scheduler_no_banner_when_all_adapters_succeed -v
```

Expected: both PASS.

- [ ] **Step 4.5: Run the full ingestion test suite to check for regressions**

Run:
```
pytest backend/tests/ingestion/ -v
```

Expected: all tests pass. Nothing else should have regressed.

- [ ] **Step 4.6: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(ingestion): end-of-run banner listing failed adapters"
```

---

## Post-Implementation Verification

- [ ] **Full backend test suite green**

Run:
```
pytest backend/tests/ -v
```

Expected: no regressions anywhere. Ingestion tests are the only ones that should have new lines; the rest is unaffected.

- [ ] **Manual sanity check — inspect a real ingest run's log output**

Run:
```
python -m backend.scripts.ingest
```

Expected observations in the terminal:
- **No** flood of `HTTP Request: POST https://openrouter.ai/...` lines from httpx (silenced).
- `stage.batch_dedup` appears if any adapter (probably Eventim) yielded duplicates; body shows `dropped={source: count}`.
- If any adapter's fetch throws, the run reaches `run.done`, the body carries `failed_adapters={...}`, and the ASCII banner appears at the end.
- No `run.failed` — the concrete IntegrityError that motivated this plan should no longer be reachable.
