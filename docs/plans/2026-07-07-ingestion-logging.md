# Ingestion Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a uniform, terminal-first log format across the ingestion pipeline so every run — scheduler, all six adapters, and all four post-fetch stages — emits the same fixed event vocabulary at the same volume.

**Architecture:** One new module `backend/app/ingestion/logging_util.py` holds a `Formatter`, a `ProgressReporter` (30s heartbeat), and a `WarningCollector` (first-per-cat WARN + rest DEBUG + summary; plus an `op()` channel for anti-bot signals). Scheduler owns a `FetchContext` per adapter and passes it into `fetch(session, ctx)`. Adapters call `ctx.progress.tick(...)` in their loops and `ctx.warns.warn(cat, detail)` / `ctx.warns.op(...)` on failure. Post-fetch stages get wrapped in a `timer()` context manager.

**Tech Stack:** Python 3.12, stdlib `logging`, pytest.

**Reference spec:** `docs/specs/2026-07-07-ingestion-logging-design.md`

---

## File Structure

**Create:**
- `backend/app/ingestion/logging_util.py` — Formatter, ProgressReporter, WarningCollector, FetchContext, null helpers, timer, configure_logging.
- `backend/tests/ingestion/test_logging_util.py` — unit tests for every helper.
- `backend/tests/ingestion/test_scheduler_logging.py` — integration test: scheduler + two fake adapters emits the expected line sequence.

**Modify:**
- `backend/app/ingestion/base.py` — extend `SourceAdapter.fetch` signature.
- `backend/app/ingestion/scheduler.py` — own FetchContext lifecycle; emit new events.
- `backend/app/ingestion/categorize.py` — add `.stats` to `CategoryCache` and `LangchainClassifier`.
- `backend/app/ingestion/normalize.py` — no logging changes needed (scheduler wraps upsert in `timer`).
- `backend/app/ingestion/dedup.py` — drop internal info line; scheduler emits `stage.dedup`.
- `backend/app/ingestion/ticketmaster.py` — add ctx; page counter; wiki_fetch/detail_fetch warnings.
- `backend/app/ingestion/eventbrite.py` — add ctx; parse_error warnings.
- `backend/app/ingestion/eventim.py` — add ctx; item counter; existing `logger.warning` → `warns.op`.
- `backend/app/ingestion/scrapers/hamburg.py` — add ctx; item counter; detail_fetch/parse_error warnings.
- `backend/app/ingestion/scrapers/ohschonhell.py` — collapse existing info/warn calls into `progress.tick` + `warns.warn`.
- `backend/app/ingestion/scrapers/theater_hamburg.py` — add ctx; item counter; parse_error warnings; keep 401 as `op`.
- `backend/app/main.py` — call `configure_logging()`; drop the inline `dictConfig`.
- `backend/scripts/ingest.py` — call `configure_logging()`.

---

## Task 1: Create `IngestionFormatter`

**Files:**
- Create: `backend/app/ingestion/logging_util.py`
- Test: `backend/tests/ingestion/test_logging_util.py`

The formatter reads `event` (str) and `body` (dict) from `LogRecord.__dict__` and produces the fixed-column line. Missing `event` → treat record as legacy and format with `record.getMessage()` as body.

- [ ] **Step 1.1: Write the failing test**

Create `backend/tests/ingestion/test_logging_util.py`:

```python
import logging

from app.ingestion.logging_util import IngestionFormatter


def _make_record(level: int, event: str, body: dict) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg="", args=(), exc_info=None,
    )
    rec.event = event
    rec.body = body
    # Fixed timestamp so tests are deterministic.
    rec.created = 1_781_308_801.0  # 2026-06-13 04:00:01 UTC-ish; formatter uses localtime
    return rec


def test_formatter_pads_columns_for_run_start():
    fmt = IngestionFormatter()
    rec = _make_record(logging.INFO, "run.start", {"run": "a3f2", "sources": 5})
    line = fmt.format(rec)
    # Expected shape: "<19 char ts> INFO  run.start           run=a3f2 sources=5"
    parts = line.split(" ", 3)  # date, time, level, tail
    assert len(parts[0]) == 10  # YYYY-MM-DD
    assert len(parts[1]) == 8   # HH:MM:SS
    assert parts[2] == "INFO "
    # Event name column is 20 chars, left-aligned.
    tail = parts[3]
    assert tail.startswith("run.start" + " " * (20 - len("run.start")))
    assert tail.endswith("run=a3f2 sources=5")


def test_formatter_renders_adapter_tag_first():
    fmt = IngestionFormatter()
    rec = _make_record(logging.INFO, "fetch.start", {"adapter": "ticketmaster"})
    line = fmt.format(rec)
    assert line.endswith("fetch.start         [ticketmaster]")


def test_formatter_renders_body_kv_pairs_in_order():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.INFO, "fetch.done",
        {"adapter": "ticketmaster", "events": 612, "pages": 11, "elapsed_s": 33.4},
    )
    line = fmt.format(rec)
    # Adapter tag first, then key=val in insertion order, elapsed rendered as "33.4s".
    assert "[ticketmaster] events=612 pages=11 elapsed=33.4s" in line


def test_formatter_renders_dict_counter_as_brace_group():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.WARNING, "fetch.done",
        {"adapter": "ticketmaster", "events": 10, "warnings": {"wiki_fetch": 8, "detail_fetch": 2}},
    )
    line = fmt.format(rec)
    assert "warnings={wiki_fetch:8, detail_fetch:2}" in line


def test_formatter_quotes_strings_with_spaces():
    fmt = IngestionFormatter()
    rec = _make_record(
        logging.WARNING, "fetch.warn",
        {"adapter": "ticketmaster", "cat": "wiki_fetch", "first": "Bad Bunny"},
    )
    line = fmt.format(rec)
    assert 'first="Bad Bunny"' in line


def test_formatter_falls_back_for_legacy_records():
    fmt = IngestionFormatter()
    rec = logging.LogRecord(
        name="app.other", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    line = fmt.format(rec)
    # Legacy path: still prints ts + level + msg. Event column is blank.
    assert "hello world" in line
    assert "INFO " in line
```

- [ ] **Step 1.2: Run test to verify it fails**

```
cd backend
pytest tests/ingestion/test_logging_util.py -v
```

Expected: `ImportError: cannot import name 'IngestionFormatter' from 'app.ingestion.logging_util'` (module does not exist yet).

- [ ] **Step 1.3: Implement `IngestionFormatter`**

Create `backend/app/ingestion/logging_util.py`:

```python
"""Uniform logging for the ingestion pipeline.

Every ingestion-related log line goes through IngestionFormatter, which
produces fixed-column output keyed on a small event vocabulary
(run.*, fetch.*, stage.*). Helpers (ProgressReporter, WarningCollector)
are added in later tasks in this same module."""
from __future__ import annotations

import logging
import time
from datetime import datetime

_EVENT_COL_WIDTH = 20
_LEVEL_COL_WIDTH = 5


def _render_value(v: object) -> str:
    """Render a body value for the k=v tail.

    - dicts render as {k:v, k:v} in insertion order (used for warnings summary)
    - strings containing whitespace are double-quoted
    - the special key elapsed_s renders as e.g. "33.4s" (see _render_body)
    - all other scalars stringify
    """
    if isinstance(v, dict):
        inner = ", ".join(f"{k}:{_render_value(val)}" for k, val in v.items())
        return "{" + inner + "}"
    if isinstance(v, str):
        if any(c.isspace() for c in v):
            escaped = v.replace('"', '\\"')
            return f'"{escaped}"'
        return v
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def _render_body(body: dict) -> str:
    """Render body dict as tail of the log line.

    - `adapter` key, if present, renders first as [name] (no key=)
    - `elapsed_s` renders as `elapsed=<Ns>` (rename + suffix)
    - remaining keys render in insertion order as key=value
    """
    parts: list[str] = []
    if "adapter" in body:
        parts.append(f"[{body['adapter']}]")
    for k, v in body.items():
        if k == "adapter":
            continue
        if k == "elapsed_s":
            parts.append(f"elapsed={v:.1f}s")
            continue
        parts.append(f"{k}={_render_value(v)}")
    return " ".join(parts)


class IngestionFormatter(logging.Formatter):
    """Fixed-column formatter for the ingestion vocabulary.

    Records must set `event` (str) and `body` (dict) attributes. Records
    without those attributes are rendered in a legacy fallback so unrelated
    library log lines still print reasonably."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname.ljust(_LEVEL_COL_WIDTH)
        event = getattr(record, "event", None)
        body = getattr(record, "body", None)
        if event is not None and isinstance(body, dict):
            event_col = event.ljust(_EVENT_COL_WIDTH)
            tail = _render_body(body)
            return f"{ts} {level} {event_col} {tail}".rstrip()
        # Legacy fallback: no event/body -- render message as-is with a
        # blank event column so the alignment stays.
        message = record.getMessage()
        return f"{ts} {level} {' ' * _EVENT_COL_WIDTH} {message}".rstrip()
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
pytest tests/ingestion/test_logging_util.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 1.5: Commit**

```
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): IngestionFormatter (fixed-column vocab lines)"
```

---

## Task 2: `configure_logging()`

Wires `IngestionFormatter` onto the root logger with a `StreamHandler`. Called once at process start. Level defaults to `INFO`.

**Files:**
- Modify: `backend/app/ingestion/logging_util.py`
- Modify: `backend/tests/ingestion/test_logging_util.py`

- [ ] **Step 2.1: Add the failing test**

Append to `backend/tests/ingestion/test_logging_util.py`:

```python
import io


def test_configure_logging_installs_formatter_on_root(capsys):
    from app.ingestion.logging_util import configure_logging

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        # Replace stdout handler with a StringIO one so we can capture.
        stream = io.StringIO()
        configure_logging(level=logging.INFO, stream=stream)
        logging.getLogger("app.ingestion.scheduler").info(
            "", extra={"event": "run.start", "body": {"run": "abcd", "sources": 2}},
        )
        output = stream.getvalue()
        assert "run.start" in output
        assert "run=abcd sources=2" in output
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
```

- [ ] **Step 2.2: Run test to verify it fails**

```
pytest tests/ingestion/test_logging_util.py::test_configure_logging_installs_formatter_on_root -v
```

Expected: `ImportError: cannot import name 'configure_logging'`.

- [ ] **Step 2.3: Implement `configure_logging`**

Append to `backend/app/ingestion/logging_util.py`:

```python
import sys


def configure_logging(level: int = logging.INFO, stream=None) -> None:
    """Install IngestionFormatter on the root logger.

    Idempotent: replaces any existing handlers we previously installed
    (identified by _INGESTION_HANDLER_MARK). Leaves foreign handlers alone
    so tests / pytest capture continue to work."""
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any handlers we previously installed.
    root.handlers = [
        h for h in root.handlers
        if not getattr(h, "_ingestion_managed", False)
    ]
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(IngestionFormatter())
    handler._ingestion_managed = True  # type: ignore[attr-defined]
    root.addHandler(handler)
```

- [ ] **Step 2.4: Run the test to verify it passes**

```
pytest tests/ingestion/test_logging_util.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 2.5: Commit**

```
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): configure_logging() installs vocab formatter"
```

---

## Task 3: `ProgressReporter`

Emits `fetch.progress` at most once per `interval_s`. `tick()` accepts cumulative counters (not deltas). `done()` returns final counters plus `elapsed_s`.

**Files:**
- Modify: `backend/app/ingestion/logging_util.py`
- Modify: `backend/tests/ingestion/test_logging_util.py`

- [ ] **Step 3.1: Add failing tests**

Append to `backend/tests/ingestion/test_logging_util.py`:

```python
def test_progress_reporter_throttles_to_interval(caplog):
    from app.ingestion.logging_util import ProgressReporter

    fake_now = [0.0]

    def clock():
        return fake_now[0]

    caplog.set_level(logging.INFO, logger="app.ingestion.progress")
    p = ProgressReporter("ticketmaster", interval_s=30.0, clock=clock)
    p.tick(page=1, events=60)              # first tick: no emission (start baseline)
    fake_now[0] = 10.0
    p.tick(page=2, events=120)             # under interval: silent
    fake_now[0] = 31.0
    p.tick(page=3, events=180)             # crossed interval: emit
    fake_now[0] = 45.0
    p.tick(page=4, events=240)             # under interval since last emit
    fake_now[0] = 62.0
    p.tick(page=5, events=300)             # crossed again: emit

    progress_records = [r for r in caplog.records if getattr(r, "event", None) == "fetch.progress"]
    assert len(progress_records) == 2
    assert progress_records[0].body == {
        "adapter": "ticketmaster", "page": 3, "events": 180, "elapsed_s": 31.0,
    }
    assert progress_records[1].body == {
        "adapter": "ticketmaster", "page": 5, "events": 300, "elapsed_s": 62.0,
    }


def test_progress_reporter_done_returns_final_state():
    from app.ingestion.logging_util import ProgressReporter

    fake_now = [0.0]
    p = ProgressReporter("ticketmaster", interval_s=30.0, clock=lambda: fake_now[0])
    p.tick(page=1, events=60)
    fake_now[0] = 33.4
    p.tick(page=11, events=612)
    result = p.done()
    assert result == {"page": 11, "events": 612, "elapsed_s": 33.4}
```

- [ ] **Step 3.2: Run tests to verify they fail**

```
pytest tests/ingestion/test_logging_util.py::test_progress_reporter_throttles_to_interval -v
```

Expected: `ImportError: cannot import name 'ProgressReporter'`.

- [ ] **Step 3.3: Implement `ProgressReporter`**

Append to `backend/app/ingestion/logging_util.py`:

```python
_progress_logger = logging.getLogger("app.ingestion.progress")


class ProgressReporter:
    """Throttled progress emitter.

    Adapters call `tick(**counters)` freely; the reporter emits `fetch.progress`
    at most once every `interval_s` seconds. The first `tick()` establishes the
    baseline start time and never emits (there is no progress to report yet).
    `done()` returns the final counter snapshot plus `elapsed_s` for the
    caller (scheduler) to fold into `fetch.done`."""

    def __init__(self, adapter: str, interval_s: float = 30.0, clock=time.monotonic):
        self._adapter = adapter
        self._interval = interval_s
        self._clock = clock
        self._start = clock()
        self._last_emit = self._start
        self._latest: dict[str, int] = {}

    def tick(self, **counters: int) -> None:
        self._latest = dict(counters)
        now = self._clock()
        if now - self._last_emit < self._interval:
            return
        self._last_emit = now
        _progress_logger.info(
            "",
            extra={
                "event": "fetch.progress",
                "body": {"adapter": self._adapter, **self._latest, "elapsed_s": now - self._start},
            },
        )

    def done(self) -> dict:
        return {**self._latest, "elapsed_s": self._clock() - self._start}
```

- [ ] **Step 3.4: Run tests to verify they pass**

```
pytest tests/ingestion/test_logging_util.py -v
```

Expected: 9 tests PASS.

- [ ] **Step 3.5: Commit**

```
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): ProgressReporter (30s throttled fetch.progress)"
```

---

## Task 4: `WarningCollector`

`warn(cat, detail)` — first per cat at WARN with detail; rest at DEBUG (silent by default); all counted. `op(msg, **fields)` — always WARN, uncounted. `summary()` — cat→count dict.

**Files:**
- Modify: `backend/app/ingestion/logging_util.py`
- Modify: `backend/tests/ingestion/test_logging_util.py`

- [ ] **Step 4.1: Add failing tests**

Append to `backend/tests/ingestion/test_logging_util.py`:

```python
def test_warning_collector_first_per_cat_warn_rest_debug(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("ticketmaster")
    w.warn("wiki_fetch", "Bad Bunny")
    w.warn("wiki_fetch", "Beyoncé")
    w.warn("detail_fetch", "id-42")
    w.warn("wiki_fetch", "Coldplay")

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warns) == 2
    assert warns[0].body == {"adapter": "ticketmaster", "cat": "wiki_fetch", "first": "Bad Bunny"}
    assert warns[1].body == {"adapter": "ticketmaster", "cat": "detail_fetch", "first": "id-42"}
    assert len(debugs) == 2  # Beyoncé, Coldplay
    assert w.summary() == {"wiki_fetch": 3, "detail_fetch": 1}


def test_warning_collector_op_always_warn_not_counted(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("eventim")
    w.op("unexpected status", status=418, url="https://example.com")
    w.op("giving up on url", url="https://example.com", attempts=4)

    ops = [r for r in caplog.records if getattr(r, "event", None) == "fetch.op"]
    assert len(ops) == 2
    assert ops[0].levelno == logging.WARNING
    assert ops[0].body == {
        "adapter": "eventim", "msg": "unexpected status",
        "status": 418, "url": "https://example.com",
    }
    assert w.summary() == {}  # op() does not count


def test_warning_collector_warn_includes_exc_info_at_debug(caplog):
    from app.ingestion.logging_util import WarningCollector

    caplog.set_level(logging.DEBUG, logger="app.ingestion.warn")
    w = WarningCollector("ohschonhell")
    try:
        raise ValueError("bad date")
    except ValueError as e:
        w.warn("bad_date", "https://example.com/x", exc=e)
        w.warn("bad_date", "https://example.com/y", exc=e)

    records = caplog.records
    # Both records carry exc_info so the traceback is preserved for DEBUG.
    assert all(r.exc_info is not None for r in records)
```

- [ ] **Step 4.2: Run tests to verify they fail**

```
pytest tests/ingestion/test_logging_util.py -v -k warning_collector
```

Expected: `ImportError: cannot import name 'WarningCollector'`.

- [ ] **Step 4.3: Implement `WarningCollector`**

Append to `backend/app/ingestion/logging_util.py`:

```python
_warn_logger = logging.getLogger("app.ingestion.warn")


class WarningCollector:
    """Per-adapter warning aggregator.

    Two channels:
      - warn(cat, detail): first per cat → WARN with detail; rest → DEBUG.
        All are counted; summary() returns the {cat: n} dict for fetch.done.
      - op(msg, **fields): always WARN, never suppressed, never counted.
        For anti-bot / operational signals that must always be visible."""

    def __init__(self, adapter: str):
        self._adapter = adapter
        self._counts: dict[str, int] = {}
        self._seen_cats: set[str] = set()

    def warn(self, cat: str, detail: str, exc: Exception | None = None) -> None:
        self._counts[cat] = self._counts.get(cat, 0) + 1
        body = {"adapter": self._adapter, "cat": cat, "first": detail}
        exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
        if cat not in self._seen_cats:
            self._seen_cats.add(cat)
            _warn_logger.warning(
                "", extra={"event": "fetch.warn", "body": body}, exc_info=exc_info,
            )
        else:
            _warn_logger.debug(
                "", extra={"event": "fetch.warn", "body": {**body, "detail": detail}},
                exc_info=exc_info,
            )

    def op(self, msg: str, **fields) -> None:
        body = {"adapter": self._adapter, "msg": msg, **fields}
        _warn_logger.warning("", extra={"event": "fetch.op", "body": body})

    def summary(self) -> dict[str, int]:
        return dict(self._counts)
```

- [ ] **Step 4.4: Run tests to verify they pass**

```
pytest tests/ingestion/test_logging_util.py -v
```

Expected: 12 tests PASS.

- [ ] **Step 4.5: Commit**

```
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): WarningCollector (aggregate warn + op channel)"
```

---

## Task 5: `FetchContext`, null helpers, `timer()`

Small glue types so scheduler can construct a context per adapter, and adapters called without a context still work (`ctx=None`). Also a `timer()` context manager for post-fetch stages so their `stage.*` line always has an `elapsed_s`.

**Files:**
- Modify: `backend/app/ingestion/logging_util.py`
- Modify: `backend/tests/ingestion/test_logging_util.py`

- [ ] **Step 5.1: Add failing tests**

Append to `backend/tests/ingestion/test_logging_util.py`:

```python
def test_fetch_context_wires_progress_and_warns():
    from app.ingestion.logging_util import FetchContext, ProgressReporter, WarningCollector

    ctx = FetchContext(
        progress=ProgressReporter("x"),
        warns=WarningCollector("x"),
    )
    assert ctx.progress is not None
    assert ctx.warns is not None


def test_null_helpers_are_safe_no_ops():
    from app.ingestion.logging_util import NullProgress, NullWarns

    p = NullProgress()
    p.tick(page=1, events=1)
    assert p.done() == {"elapsed_s": 0.0}

    w = NullWarns()
    w.warn("cat", "detail")
    w.op("msg", key="value")
    assert w.summary() == {}


def test_timer_emits_stage_event_with_elapsed(caplog):
    from app.ingestion.logging_util import timer

    fake_now = [100.0]
    caplog.set_level(logging.INFO, logger="app.ingestion.stage")
    body: dict = {"inserted": 0}
    with timer("stage.upsert", body=body, clock=lambda: fake_now[0]):
        body["inserted"] = 42
        fake_now[0] = 100.5

    records = [r for r in caplog.records if getattr(r, "event", None) == "stage.upsert"]
    assert len(records) == 1
    assert records[0].body == {"inserted": 42, "elapsed_s": 0.5}
```

- [ ] **Step 5.2: Run tests to verify they fail**

```
pytest tests/ingestion/test_logging_util.py -v -k "fetch_context or null_helpers or timer"
```

Expected: `ImportError: cannot import name 'FetchContext'`.

- [ ] **Step 5.3: Implement `FetchContext`, null helpers, `timer`**

Append to `backend/app/ingestion/logging_util.py`:

```python
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class FetchContext:
    """Bundle handed to SourceAdapter.fetch by the scheduler.

    Scheduler owns lifecycle: constructs one per adapter, passes it in,
    reads progress.done() and warns.summary() after the generator drains,
    folds them into the fetch.done line."""
    progress: "ProgressReporter | NullProgress"
    warns: "WarningCollector | NullWarns"


class NullProgress:
    """No-op ProgressReporter for adapters called with ctx=None (tests, CLI)."""
    def tick(self, **counters: int) -> None: ...
    def done(self) -> dict: return {"elapsed_s": 0.0}


class NullWarns:
    """No-op WarningCollector for adapters called with ctx=None."""
    def warn(self, cat: str, detail: str, exc: Exception | None = None) -> None: ...
    def op(self, msg: str, **fields) -> None: ...
    def summary(self) -> dict[str, int]: return {}


_stage_logger = logging.getLogger("app.ingestion.stage")


@contextmanager
def timer(event: str, body: dict, clock=time.monotonic):
    """Time a block; on exit, emit `event` with `body` + elapsed_s.

    Body is a mutable dict; mutate it inside the block to accumulate counters
    (e.g. cache_hits, llm_calls). The clock kwarg is for test injection."""
    start = clock()
    try:
        yield body
    finally:
        body["elapsed_s"] = clock() - start
        _stage_logger.info("", extra={"event": event, "body": dict(body)})
```

- [ ] **Step 5.4: Run tests to verify they pass**

```
pytest tests/ingestion/test_logging_util.py -v
```

Expected: 15 tests PASS.

- [ ] **Step 5.5: Commit**

```
git add backend/app/ingestion/logging_util.py backend/tests/ingestion/test_logging_util.py
git commit -m "feat(ingestion): FetchContext, null helpers, timer()"
```

---

## Task 6: Wire `configure_logging()` into `main.py` and `scripts/ingest.py`

Replace the ad-hoc `dictConfig` in `main.py` and add a call at the top of the CLI entry point so both paths install `IngestionFormatter`.

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/scripts/ingest.py`

- [ ] **Step 6.1: Replace `dictConfig` in `main.py`**

In `backend/app/main.py`, replace lines 1-29 (the `import logging`/`import logging.config` block and the `logging.config.dictConfig({...})` call) with:

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_appointments, routes_calendar, routes_chat, routes_digest, routes_events, routes_feedback, routes_profile
from app.api.deps import current_user_id_middleware
from app.config import settings
from app.db import run_migrations
from app.db.models import User
from app.db.session import SessionLocal
from app.ingestion.logging_util import configure_logging
from app.ingestion.scheduler import create_scheduler, run_ingestion

configure_logging()
```

Everything from `logger = logging.getLogger(__name__)` onward stays the same.

- [ ] **Step 6.2: Add configure_logging to `scripts/ingest.py`**

In `backend/scripts/ingest.py`, modify the `main()` function to configure logging first:

```python
"""Run the full ingestion pipeline once and exit.

Standalone trigger for the same `run_ingestion()` that the APScheduler cron
job and `POST /ingestion/run` use. No FastAPI app, no uvicorn — safe to call
from OS-cron / Windows Task Scheduler so the daily run does not depend on a
long-running backend process.

Usage from backend/: `python -m scripts.ingest`
"""
from __future__ import annotations

import sys

from app.ingestion.logging_util import configure_logging
from app.ingestion.scheduler import run_ingestion


def main() -> int:
    configure_logging()
    try:
        report = run_ingestion()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the caller
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"inserted={report.inserted} updated={report.updated} skipped={report.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6.3: Verify existing tests still pass**

```
cd backend
pytest tests/api/test_main.py -v
pytest tests/ingestion -v
```

Expected: all tests PASS. If any depended on the exact log format, update assertions to the new column format.

- [ ] **Step 6.4: Commit**

```
git add backend/app/main.py backend/scripts/ingest.py
git commit -m "feat(ingestion): wire configure_logging() into main and CLI"
```

---

## Task 7: Extend `SourceAdapter.fetch` signature in `base.py`

Add an optional `ctx: FetchContext | None = None` parameter. Default None keeps all existing adapters and tests working — they simply ignore the parameter for now.

**Files:**
- Modify: `backend/app/ingestion/base.py`

- [ ] **Step 7.1: Extend the Protocol**

Replace the contents of `backend/app/ingestion/base.py`:

```python
from typing import Iterator, Protocol

from sqlalchemy.orm import Session

from app.ingestion.logging_util import FetchContext
from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(
        self,
        session: Session,
        ctx: FetchContext | None = None,
    ) -> Iterator[NormalizedEvent]: ...
```

- [ ] **Step 7.2: Verify existing adapter tests still pass**

```
cd backend
pytest tests/ingestion -v
```

Expected: all tests PASS (adapters don't yet accept `ctx` — Protocol is structural, not enforced at construction).

- [ ] **Step 7.3: Commit**

```
git add backend/app/ingestion/base.py
git commit -m "feat(ingestion): SourceAdapter.fetch accepts optional FetchContext"
```

---

## Task 8: Refactor `scheduler.py` to use the new vocabulary

Scheduler owns `FetchContext` per adapter, emits `run.*` / `fetch.*` / `stage.*` events, wraps each stage in `timer()`, and formats the summary using the vocabulary. Removes the ad-hoc `[adapter]` info lines it currently emits.

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`

- [ ] **Step 8.1: Rewrite `run_ingestion`**

Replace the body of `run_ingestion` in `backend/app/ingestion/scheduler.py` (starting after the `_default_adapters` function) with the following. Keep imports at the top; add the new ones.

New imports (add at top of file):

```python
import secrets
import time

from app.ingestion.logging_util import (
    FetchContext, ProgressReporter, WarningCollector, timer,
)
```

Rewritten body:

```python
def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
    classifier: LLMClassifier | None = None,
) -> UpsertReport:
    """Fetch all sources, upsert to DB, deactivate past events.

    Emits the standard ingestion vocabulary: run.start, per-adapter
    fetch.start/fetch.done (or fetch.skipped/fetch.failed), stage.categorize,
    stage.upsert, stage.dedup, stage.embed, run.done."""
    own_wiki_client = adapters is None
    wiki_client = httpx.Client(timeout=15) if own_wiki_client else None
    if adapters is None:
        adapters = _default_adapters(wiki_client=wiki_client)

    own_session = session is None
    if own_session:
        run_migrations()
        session = SessionLocal()

    if classifier is None:
        classifier = LangchainClassifier()

    run_id = secrets.token_hex(2)
    run_start = time.monotonic()
    run_logger = logging.getLogger("app.ingestion.run")
    run_logger.info("", extra={"event": "run.start", "body": {"run": run_id, "sources": len(adapters)}})

    per_adapter_counts: dict[str, int | None] = {}
    total_events = 0

    try:
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events: list = []

        for adapter in adapters:
            state = session.get(IngestionState, adapter.name)
            tripped = state is not None and state.disabled_at is not None
            fetch_logger = logging.getLogger("app.ingestion.fetch")

            if tripped:
                fetch_logger.warning(
                    "",
                    extra={
                        "event": "fetch.skipped",
                        "body": {
                            "adapter": adapter.name,
                            "reason": "breaker-tripped",
                            "since": state.disabled_at.date().isoformat(),
                        },
                    },
                )
                per_adapter_counts[adapter.name] = None
                continue

            fetch_logger.info(
                "", extra={"event": "fetch.start", "body": {"adapter": adapter.name}}
            )
            ctx = FetchContext(
                progress=ProgressReporter(adapter.name),
                warns=WarningCollector(adapter.name),
            )
            t0 = time.monotonic()
            try:
                batch = list(adapter.fetch(session, ctx))
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
                per_adapter_counts[adapter.name] = None
                continue

            counters = ctx.progress.done()
            warnings_summary = ctx.warns.summary()
            body: dict = {"adapter": adapter.name, "events": len(batch)}
            # Merge counters (page=…, events=…) but avoid double-writing events.
            counters.pop("events", None)
            body.update(counters)
            if warnings_summary:
                body["warnings"] = warnings_summary
            fetch_logger.info("", extra={"event": "fetch.done", "body": body})

            all_events.extend(batch)
            per_adapter_counts[adapter.name] = len(batch)
            total_events += len(batch)

        # --- Categorization ---
        stats = {"events": len(all_events), "cache_hits": 0, "llm_calls": 0}
        with timer("stage.categorize", body=stats):
            for ev in all_events:
                ev.category = refine_category(ev, cache, classifier)
            stats["cache_hits"] = cache.stats["hits"]
            stats["llm_calls"] = classifier.stats["calls"]

        # --- Upsert ---
        upsert_body: dict = {}
        with timer("stage.upsert", body=upsert_body):
            report = upsert_events(session, all_events)
            deactivate_past_events(session)
            upsert_body.update(
                inserted=report.inserted, updated=report.updated, skipped=report.skipped,
            )

        # --- Dedup ---
        dedup_body: dict = {}
        with timer("stage.dedup", body=dedup_body):
            dr = dedup_events(session)
            dedup_body.update(groups=dr.groups_found, merged=dr.rows_merged)

        # --- Embed ---
        embed_body: dict = {}
        with timer("stage.embed", body=embed_body):
            embed_new_events(session, body=embed_body)

        if own_session:
            session.commit()

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
    except Exception as exc:
        if own_session:
            session.rollback()
        run_logger.exception(
            "",
            extra={
                "event": "run.failed",
                "body": {
                    "err": type(exc).__name__,
                    "elapsed_s": time.monotonic() - run_start,
                },
            },
        )
        raise
    finally:
        if own_session:
            session.close()
        if own_wiki_client and wiki_client is not None:
            wiki_client.close()
```

- [ ] **Step 8.2: Update `embed_new_events` to accept `body` dict**

Replace `embed_new_events` in `backend/app/ingestion/scheduler.py`:

```python
def embed_new_events(session: Session, body: dict | None = None) -> None:
    """Embed all currently-visible events into Chroma and drop stale vectors.

    Stale = a Chroma id whose event no longer passes visible_events_filter()
    (deleted, deactivated, or — when the hide toggle is on — missing a
    description). Idempotent: upsert by id, delete by id.

    If `body` is provided (used by the scheduler's stage.embed timer),
    it is populated with `upserted` and `purged` counts."""
    visible_ids = {
        row[0]
        for row in session.query(Event.id).filter(visible_events_filter()).all()
    }
    stale = list(chroma_store.all_ids() - visible_ids)
    if stale:
        chroma_store.delete_by_ids(stale)

    rows = session.query(Event).filter(visible_events_filter()).all()
    payload = [
        EventForEmbedding(
            id=r.id,
            title=r.title,
            description=r.description,
            category=r.category,
            venue_name=r.venue_name,
            neighborhood=None,
            start_datetime=r.start_datetime,
        )
        for r in rows
    ]
    if payload:
        chroma_upsert_events(payload)
    if body is not None:
        body["upserted"] = len(payload)
        body["purged"] = len(stale)
```

- [ ] **Step 8.3: Delete the old summary block**

The section `# Per-adapter summary at end of run` (currently at scheduler.py:144-154) and the trailing `logger.info("Ingestion complete — inserted=... ")` are superseded by `fetch.done` per adapter plus `run.done`. Delete these lines in the rewritten function above.

- [ ] **Step 8.4: Run scheduler tests to confirm they still pass**

```
cd backend
pytest tests/ingestion -v
```

Expected: existing tests PASS. Some tests may reference the old summary log format (`"ingest summary:"`, `"Ingestion complete"`); update those assertions to look for `run.done` in the log output.

- [ ] **Step 8.5: Commit**

```
git add backend/app/ingestion/scheduler.py
git commit -m "feat(ingestion): scheduler emits run/fetch/stage vocabulary"
```

---

## Task 9: Add `.stats` to `CategoryCache` and `LangchainClassifier`

Track hits and calls so the scheduler can populate `stage.categorize` body with `cache_hits` and `llm_calls`.

**Files:**
- Modify: `backend/app/ingestion/categorize.py`
- Modify: `backend/tests/ingestion/test_categorize.py` (if it exists — otherwise skip test creation)

- [ ] **Step 9.1: Add stats dict to `CategoryCache`**

In `backend/app/ingestion/categorize.py`, modify `CategoryCache`:

```python
class CategoryCache:
    """Thin wrapper over `event_category_cache` for get/set-by-hash access."""

    def __init__(self, session: Session, model_name: str):
        self._session = session
        self._model_name = model_name
        self.stats = {"hits": 0}

    def get(self, content_hash: str) -> str | None:
        row = (
            self._session.query(EventCategoryCache)
            .filter_by(content_hash=content_hash)
            .one_or_none()
        )
        if row is not None:
            self.stats["hits"] += 1
            return row.category
        return None

    def set(self, content_hash: str, category: str) -> None:
        stmt = sqlite_insert(EventCategoryCache).values(
            content_hash=content_hash,
            category=category,
            model=self._model_name,
        ).on_conflict_do_nothing(index_elements=["content_hash"])
        self._session.execute(stmt)
```

- [ ] **Step 9.2: Add stats dict to `LangchainClassifier`**

In `backend/app/ingestion/categorize.py`, modify `LangchainClassifier`:

```python
class LangchainClassifier:
    """Concrete `LLMClassifier` backed by a LangChain chat model with
    structured output. Constructed once per ingestion run; safe to reuse."""

    def __init__(self, llm: ChatOpenAI | None = None):
        base = llm if llm is not None else build_categorization_llm()
        self._structured = base.with_structured_output(CategoryDecision)
        self.stats = {"calls": 0}

    def classify(self, event: NormalizedEvent) -> CategoryDecision:
        self.stats["calls"] += 1
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=render_user_prompt(event)),
        ]
        return self._structured.invoke(messages)
```

- [ ] **Step 9.3: Verify tests still pass**

```
cd backend
pytest tests/ingestion -v
```

Expected: all tests PASS. Any test that injects a fake classifier must also give it a `.stats = {"calls": 0}` attribute so scheduler.run_ingestion can read it. Update fake classifiers accordingly.

- [ ] **Step 9.4: Commit**

```
git add backend/app/ingestion/categorize.py
git commit -m "feat(ingestion): CategoryCache + LangchainClassifier expose .stats"
```

---

## Task 10: Migrate `ticketmaster.py`

Accept `ctx`; add page/event counters via `ctx.progress`; route wiki_fetch and detail_fetch failures through `ctx.warns.warn(...)`.

**Files:**
- Modify: `backend/app/ingestion/ticketmaster.py`

- [ ] **Step 10.1: Update `fetch` and helper signatures**

In `backend/app/ingestion/ticketmaster.py`:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns


class TicketmasterAdapter:
    name = "ticketmaster"

    def __init__(
        self,
        client: httpx.Client | None = None,
        wiki_client: httpx.Client | None = None,
    ):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key
        self._wiki_client = wiki_client
        self._wiki_cache: dict[str, str | None] = {}

    def fetch(self, session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        params: dict = {
            "city": "Hamburg",
            "countryCode": "DE",
            "size": 200,
            "page": 0,
        }
        if self._api_key:
            params["apikey"] = self._api_key

        events = 0
        page_num = 0
        while True:
            page_num += 1
            resp = self._client.get(f"{_BASE_URL}/events.json", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("_embedded", {}).get("events", []):
                detail = self._fetch_detail(raw.get("id", ""), warns)
                event = self._parse(raw, detail, warns)
                if event:
                    events += 1
                    yield event

            progress.tick(page=page_num, events=events)

            page_info = data.get("page", {})
            total = page_info.get("totalPages", 1)
            current = page_info.get("number", 0)
            if current + 1 >= total:
                break
            params["page"] = current + 1

    def _fetch_detail(self, event_id: str, warns) -> dict:
        if not event_id:
            return {}
        params = {"apikey": self._api_key} if self._api_key else {}
        try:
            resp = self._client.get(f"{_BASE_URL}/events/{event_id}.json", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            warns.warn("detail_fetch", event_id, exc=e)
            return {}
```

- [ ] **Step 10.2: Update `_lookup_wiki_summary` and `_parse` to accept warns**

```python
    def _fetch_wiki_description_for_event(self, raw: dict, warns) -> str | None:
        if self._wiki_client is None:
            return None
        for att in (raw.get("_embedded") or {}).get("attractions") or []:
            wiki_links = ((att.get("externalLinks") or {}).get("wiki")) or []
            for link in wiki_links:
                url = link.get("url") if isinstance(link, dict) else None
                desc = self._lookup_wiki_summary(url, warns)
                if desc:
                    return desc
        return None

    def _lookup_wiki_summary(self, url: str | None, warns) -> str | None:
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
        except Exception as e:
            warns.warn("wiki_fetch", api, exc=e)
            self._wiki_cache[url] = None
            return None
        text = extract_summary(body)
        self._wiki_cache[url] = text
        return text

    def _parse(self, raw: dict, detail: dict | None = None, warns=None) -> NormalizedEvent | None:
        if warns is None:
            warns = NullWarns()
        try:
            # ... existing parse body up to the description block, unchanged ...
            description: str | None = None
            if detail:
                description = (
                    detail.get("info") or detail.get("additionalInfo") or detail.get("pleaseNote")
                ) or None
            if not description:
                description = self._fetch_wiki_description_for_event(raw, warns)
            # ... rest of parse body, unchanged, up to and including the except: ...
        except (KeyError, ValueError, TypeError) as e:
            warns.warn("parse_error", str(raw.get("id", "<no-id>")), exc=e)
            return None
```

Note: the full `_parse` body is unchanged except for these three edits — the description line calls `_fetch_wiki_description_for_event(raw, warns)`, the signature adds `warns=None`, and the `except` uses `warns.warn(...)`. Preserve every other line as-is.

- [ ] **Step 10.3: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k ticketmaster
```

Expected: PASS. Tests that call `.fetch(session)` without ctx use the NullWarns fallback — still work.

- [ ] **Step 10.4: Commit**

```
git add backend/app/ingestion/ticketmaster.py
git commit -m "feat(ingestion): ticketmaster uses ProgressReporter + WarningCollector"
```

---

## Task 11: Migrate `scrapers/hamburg.py`

Accept `ctx`; add item counter; route detail_fetch/parse_error through `ctx.warns.warn(...)`.

**Files:**
- Modify: `backend/app/ingestion/scrapers/hamburg.py`

- [ ] **Step 11.1: Update `fetch` and helpers**

In `backend/app/ingestion/scrapers/hamburg.py`:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns


class HamburgScraper:
    name = "hamburg_scraper"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": "EventTrackerBot/1.0"}
        )

    def fetch(self, session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        resp = self._client.get(_BASE_URL)
        resp.raise_for_status()

        today = datetime.now(tz=_BERLIN).date()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen: set[str] = set()
        events = 0
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if not href.startswith("/event/"):
                continue
            if link.find("img"):
                continue
            title = link.get_text(strip=True)
            if not title:
                continue
            slug = href.split("/event/", 1)[1].split("/")[0]
            if not slug or slug in seen:
                continue
            seen.add(slug)

            description = self._fetch_description(slug, warns)
            ev = self._parse_card(link, slug, title, today, description=description, warns=warns)
            if ev:
                events += 1
                progress.tick(events=events)
                yield ev

    def _fetch_description(self, slug: str, warns) -> str | None:
        url = f"{_BASE_URL}/event/{slug}"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except Exception as e:
            warns.warn("detail_fetch", slug, exc=e)
            return None
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            el = soup.find("meta", attrs={"name": "description"})
            if el:
                text = el.get("content", "").strip()
                return text or None
            return None
        except Exception as e:
            warns.warn("detail_parse", slug, exc=e)
            return None

    def _parse_card(
        self,
        title_link,
        slug: str,
        title: str,
        today: date,
        description: str | None = None,
        warns=None,
    ) -> NormalizedEvent | None:
        if warns is None:
            warns = NullWarns()
        try:
            # ... existing parse body, unchanged, up to the except at the end ...
        except Exception as e:
            warns.warn("parse_error", slug, exc=e)
            return None
```

Preserve the entire body of `_parse_card` — only the signature adds `warns=None`, and the `except Exception:` becomes `except Exception as e: warns.warn("parse_error", slug, exc=e); return None`.

- [ ] **Step 11.2: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k hamburg
```

Expected: PASS.

- [ ] **Step 11.3: Commit**

```
git add backend/app/ingestion/scrapers/hamburg.py
git commit -m "feat(ingestion): hamburg scraper uses ProgressReporter + WarningCollector"
```

---

## Task 12: Migrate `scrapers/ohschonhell.py`

The noisiest adapter today. Delete the internal `_PROGRESS_INTERVAL_SECONDS` block, the manual `last_log_at` counter, the summary `logger.info` at the end. Replace with `ctx.progress.tick()` and `ctx.warns.warn(...)`. Keep the retry helpers unchanged (they use their own `RetryStats`) but route their `logger.warning` calls to `warns.op(...)` — HTTP 429/503 patterns are borderline operational, but on this site they're not anti-bot, so let them be aggregated `warn` under cat `http_retry`.

**Files:**
- Modify: `backend/app/ingestion/scrapers/ohschonhell.py`

- [ ] **Step 12.1: Update `fetch`**

In `backend/app/ingestion/scrapers/ohschonhell.py`, replace the entire `fetch()` method:

```python
    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        last_seen = get_last_seen(session, self.name)
        if last_seen is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_BOOTSTRAP_WINDOW_DAYS)
        else:
            cutoff = last_seen

        stats = RetryStats()
        sitemap_body = get_with_retry(
            self._client, _SITEMAP_URL, stats=stats, sleep_fn=self._sleep_fn, warns=warns,
        )
        if sitemap_body is None:
            raise RuntimeError("ohschonhell: sitemap fetch failed after retries")
        candidates = filter_sitemap(sitemap_body, cutoff)

        max_lastmod: datetime | None = None
        parsed_count = 0

        for i, (url, lastmod) in enumerate(candidates):
            if i > 0:
                self._sleep_fn(_REQUEST_DELAY_SECONDS)

            body = get_with_retry(
                self._client, url, stats=stats, sleep_fn=self._sleep_fn, warns=warns,
            )
            if body is None:
                warns.warn("http_error", url)
                continue

            parsed = parse_event(body)
            if parsed is None:
                warns.warn("parse_error", url)
                continue

            try:
                naive = datetime.fromisoformat(f"{parsed['date']}T{parsed['time']}")
                start_dt = naive.replace(tzinfo=_BERLIN)
            except ValueError as e:
                warns.warn("bad_date", url, exc=e)
                continue

            slug = url.rsplit("/date/", 1)[-1]
            venue_address = ", ".join(
                p for p in [parsed["street"], f"{parsed['postal_code']} {parsed['city']}".strip()] if p
            ).strip(", ")

            yield NormalizedEvent(
                external_id=parsed["event_id"],
                source=self.name,
                title=parsed["name"],
                description=parsed["description"],
                start_datetime=start_dt,
                venue_name=parsed["venue_name"],
                venue_address=venue_address or None,
                category="party",
                tags=["party"],
                is_free=False,
                currency="EUR",
                image_url=parsed["image_url"],
                source_url=url,
                raw_data={
                    "event_id": parsed["event_id"],
                    "slug": slug,
                    "sitemap_lastmod": lastmod.isoformat(),
                },
            )
            parsed_count += 1
            progress.tick(parsed=parsed_count, seen=i + 1, total=len(candidates))
            if max_lastmod is None or lastmod > max_lastmod:
                max_lastmod = lastmod

        if max_lastmod is not None:
            set_last_seen(session, self.name, max_lastmod)
```

- [ ] **Step 12.2: Update `get_with_retry` to accept `warns`**

Replace `get_with_retry` in `backend/app/ingestion/scrapers/ohschonhell.py`:

```python
def get_with_retry(
    client: _HttpGetter,
    url: str,
    *,
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
    warns=None,
) -> str | None:
    """GET `url` with exponential backoff on 429/503. Returns body text or None."""
    from app.ingestion.logging_util import NullWarns
    if warns is None:
        warns = NullWarns()
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.content.decode("utf-8", errors="replace")
        if resp.status_code not in _RETRY_STATUS_CODES:
            warns.warn("http_status", f"{resp.status_code} {url}")
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            warns.warn("http_retry_exhausted", url)
    return None
```

- [ ] **Step 12.3: Remove now-unused imports and constants**

Delete the constant `_PROGRESS_INTERVAL_SECONDS = 30` (line 229) — replaced by `ProgressReporter`. Delete the `import time` if it's no longer used (it may still be needed for `sleep_fn=time.sleep` default). Verify by trying `python -c "import app.ingestion.scrapers.ohschonhell"`.

- [ ] **Step 12.4: Add FetchContext + NullProgress + NullWarns imports**

At the top of the file, add:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns
```

- [ ] **Step 12.5: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k ohschonhell
```

Expected: PASS. Tests that assert on log content need to be updated to check for `WarningCollector` cat labels instead of the old free-form strings.

- [ ] **Step 12.6: Commit**

```
git add backend/app/ingestion/scrapers/ohschonhell.py
git commit -m "feat(ingestion): ohschonhell uses ProgressReporter + WarningCollector"
```

---

## Task 13: Migrate `scrapers/theater_hamburg.py`

Accept `ctx`; count events; route `parse_error` through `warns.warn`; keep the `401 → re-scrape JWT` line as `warns.op(...)` (operational — an anti-bot-adjacent signal).

**Files:**
- Modify: `backend/app/ingestion/scrapers/theater_hamburg.py`

- [ ] **Step 13.1: Update `fetch` and `_post` and `_expand_node`**

In `backend/app/ingestion/scrapers/theater_hamburg.py`:

Add to imports:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns
```

Replace `fetch`:

```python
    def fetch(self, session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        today = datetime.now(tz=_BERLIN).date().isoformat()
        page = 1
        emitted: set[str] = set()
        events = 0
        while True:
            data = self._list_page(page, today, warns)
            events_root = (data.get("data") or {}).get("events") or {}
            nodes = events_root.get("nodes") or []
            pagination = events_root.get("pagination") or {}
            total_pages = pagination.get("totalPages", 1)

            for node in nodes:
                for parsed in self._expand_node(node, warns):
                    if parsed.external_id in emitted:
                        continue
                    emitted.add(parsed.external_id)
                    events += 1
                    yield parsed
            progress.tick(page=page, events=events)

            if page >= total_pages or not nodes:
                break
            page += 1
```

Replace `_post` and `_list_page` to thread `warns`:

```python
    def _post(self, body: dict, warns=None) -> dict:
        """POST to GraphQL, transparently re-scraping JWT once on 401."""
        if warns is None:
            warns = NullWarns()
        jwt = self._get_jwt()
        resp = self._client.post(
            _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
        )
        if resp.status_code == 401:
            warns.op("jwt-rescrape", reason="401")
            self._jwt = None
            jwt = self._rescrape_jwt()
            resp = self._client.post(
                _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
            )
        resp.raise_for_status()
        return resp.json()

    def _list_page(self, page: int, from_date: str, warns=None) -> dict:
        variables = {
            "filter": {
                "and": [
                    {"or": [
                        {"eventLocation": {"id": {"oneOf": _LOCATION_IDS}}},
                        {"eventLocation": {"group": {"oneOf": _GROUP_IDS}}},
                    ]},
                    {"fromDate": from_date},
                ]
            },
            "pagination": {"page": page, "pageSize": _PAGE_SIZE},
            "appearance": {"deliveryChannel": 76},
        }
        body = {"query": _LIST_QUERY, "variables": variables}
        return self._post(body, warns=warns)
```

Update `_expand_node` to accept and use `warns`:

```python
    def _expand_node(self, node: dict, warns=None) -> Iterator[NormalizedEvent]:
        if warns is None:
            warns = NullWarns()
        permalink = node.get("permaLink") or ""
        # ... existing body, unchanged, up to the except at the end of the for loop ...
        for ed in node.get("eventDates") or []:
            date = ed.get("date")
            start_time = ed.get("startTime")
            if not date:
                continue
            try:
                start = _parse_start(date, start_time)
                external_id = f"{permalink}#{date}T{start_time or '00:00'}"
                yield NormalizedEvent(
                    # ... unchanged NormalizedEvent construction ...
                )
            except (KeyError, ValueError, TypeError) as e:
                warns.warn("parse_error", permalink, exc=e)
```

- [ ] **Step 13.2: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k theater_hamburg
```

Expected: PASS.

- [ ] **Step 13.3: Commit**

```
git add backend/app/ingestion/scrapers/theater_hamburg.py
git commit -m "feat(ingestion): theater_hamburg uses ProgressReporter + WarningCollector"
```

---

## Task 14: Migrate `eventim.py` (operational warnings intact)

Accept `ctx`; count events for progress; migrate every existing `logger.warning(...)` call to `warns.op(...)` per the anti-bot policy in the spec. Keep the circuit-breaker banner logs as-is (they render via multi-line strings and are important operational context — leave them via `logger.warning` because they intentionally use ASCII-art banners). The circuit-breaker banners can either stay verbatim or migrate to `warns.op("circuit-breaker-tripped", ...)`; keep them as `logger.warning` verbatim to preserve the operator-facing banner formatting.

**Files:**
- Modify: `backend/app/ingestion/eventim.py`

- [ ] **Step 14.1: Thread `warns` through `get_json_with_retry` and `_category_for`**

Replace `get_json_with_retry`:

```python
def get_json_with_retry(
    client: _HttpGetter,
    url: str,
    *,
    params: dict[str, Any],
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
    warns=None,
) -> dict | None:
    """GET a JSON endpoint with exponential backoff on 403/429/503."""
    from app.ingestion.logging_util import NullWarns
    if warns is None:
        warns = NullWarns()
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url, params=params)
        if 200 <= resp.status_code < 300:
            return resp.json()
        if resp.status_code == 403:
            stats.akamai_403s += 1
            ref = _extract_akamai_ref(resp.text or "")
            if ref and len(stats.akamai_refs) < _AKAMAI_REF_MAX:
                stats.akamai_refs.append(ref)
        if resp.status_code not in _RETRY_STATUS_CODES:
            warns.op("unexpected-status", status=resp.status_code, url=url)
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            warns.op(
                "retry-backoff",
                status=resp.status_code, url=url, backoff_s=backoff,
                attempt=attempt, max=_RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            warns.op("retry-exhausted", url=url, attempts=_RETRY_MAX_ATTEMPTS)
    return None
```

- [ ] **Step 14.2: Migrate `_category_for` unknown-leaf warning**

Replace the `logger.warning(...)` inside `_category_for`. Since `_category_for` has no `warns` in scope today, thread it through: change signature to `_category_for(product: dict, warns) -> EventCategory`, and its two callsites in `parse_product` need the same change. Since `parse_product` also lacks `warns`, add it as an optional parameter:

```python
def _category_for(product: dict, warns) -> EventCategory:
    for cat in product.get("categories", []):
        parent = cat.get("parentCategory")
        if not parent:
            continue
        name = cat.get("name")
        mapped = _CATEGORY_MAP.get(name)
        if mapped is not None:
            return mapped
        warns.warn("unknown-category-leaf", str(name))
        return "other"
    return "other"


def parse_product(product: dict, warns=None) -> NormalizedEvent | None:
    """Convert one Eventim product dict to a NormalizedEvent."""
    from app.ingestion.logging_util import NullWarns
    if warns is None:
        warns = NullWarns()
    # ... existing body, unchanged, except: ...
    # Change: category=_category_for(product, warns),
```

- [ ] **Step 14.3: Update `EventimAdapter.fetch` to accept ctx and thread warns**

Replace `fetch`:

```python
    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        state = session.get(IngestionState, self.name)
        if state is not None and state.disabled_at is not None:
            self._log_disabled_banner(state)
            self._bump_runs_while_disabled()
            return

        stats = RetryStats()
        categories_failed_page_1 = 0
        consecutive_exhaustions = 0
        events_yielded_this_run = 0

        for i, category in enumerate(_CATEGORIES):
            first = get_json_with_retry(
                self._client, _API,
                params=self._params(category, page=1),
                stats=stats, sleep_fn=self._sleep_fn, warns=warns,
            )
            if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                           events_yielded_this_run, category, i)
                return
            if first is None:
                warns.op("category-page-1-failed", category=category)
                categories_failed_page_1 += 1
                continue

            for ev in self._products(first, warns):
                events_yielded_this_run += 1
                progress.tick(category=category, events=events_yielded_this_run)
                yield ev

            total_pages = int(first.get("totalPages") or 1)
            for page in range(2, total_pages + 1):
                self._sleep_fn(_REQUEST_DELAY_SECONDS)
                body = get_json_with_retry(
                    self._client, _API,
                    params=self._params(category, page=page),
                    stats=stats, sleep_fn=self._sleep_fn, warns=warns,
                )
                if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                    self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                               events_yielded_this_run, category, i)
                    return
                if body is None:
                    warns.op("category-page-failed", category=category, page=page)
                    consecutive_exhaustions += 1
                    if consecutive_exhaustions >= self._TRIP_CONSECUTIVE_EXHAUSTIONS:
                        self._trip(
                            f"consecutive_retry_exhaustion: {consecutive_exhaustions} pages",
                            events_yielded_this_run, category, i,
                        )
                        return
                    continue
                consecutive_exhaustions = 0
                for ev in self._products(body, warns):
                    events_yielded_this_run += 1
                    progress.tick(category=category, events=events_yielded_this_run)
                    yield ev

        if categories_failed_page_1 == len(_CATEGORIES):
            self._trip("all_categories_failed_page_1",
                       events_yielded_this_run,
                       _CATEGORIES[-1], len(_CATEGORIES) - 1)
            return

    def _products(self, body: dict, warns) -> Iterator[NormalizedEvent]:
        for product in body.get("products", []) or []:
            ev = parse_product(product, warns)
            if ev is not None:
                yield ev
```

Add imports at top of file:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns
```

Keep `_trip`, `_log_disabled_banner`, `_bump_runs_while_disabled`, `_params` unchanged — the ASCII banners in `_trip` and `_log_disabled_banner` continue to go through `logger.warning` verbatim.

- [ ] **Step 14.4: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k eventim
```

Expected: PASS. Tests that inspected `caplog.records` for exact WARN strings from `get_json_with_retry` need updating — those are now `fetch.op` records with `body["msg"]` = short slug (`"unexpected-status"`, `"retry-backoff"`, `"retry-exhausted"`) and typed fields.

- [ ] **Step 14.5: Commit**

```
git add backend/app/ingestion/eventim.py
git commit -m "feat(ingestion): eventim routes operational warnings via WarningCollector.op"
```

---

## Task 15: Migrate `eventbrite.py`

Small edit — Eventbrite is optional and short.

**Files:**
- Modify: `backend/app/ingestion/eventbrite.py`

- [ ] **Step 15.1: Update fetch and `_parse` signatures**

In `backend/app/ingestion/eventbrite.py`:

```python
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns


class EventbriteAdapter:
    name = "eventbrite"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._token = settings.eventbrite_token

    def fetch(self, session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        params: dict = {
            "location.address": "Hamburg, Germany",
            "location.within": "20km",
            "expand": "venue,category,ticket_availability",
            "page_size": 50,
        }
        if self._token:
            params["token"] = self._token

        continuation: str | None = None
        page_num = 0
        events = 0
        while True:
            page_num += 1
            if continuation:
                params["continuation"] = continuation

            resp = self._client.get(f"{_BASE_URL}/events/search/", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("events", []):
                event = self._parse(raw, warns)
                if event:
                    events += 1
                    yield event
            progress.tick(page=page_num, events=events)

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break
            continuation = pagination.get("continuation")
            if not continuation:
                break

    def _parse(self, raw: dict, warns=None) -> NormalizedEvent | None:
        if warns is None:
            warns = NullWarns()
        try:
            # ... existing body, unchanged ...
        except (KeyError, ValueError, TypeError) as e:
            warns.warn("parse_error", str(raw.get("id", "<no-id>")), exc=e)
            return None
```

- [ ] **Step 15.2: Run adapter tests**

```
cd backend
pytest tests/ingestion -v -k eventbrite
```

Expected: PASS (or SKIP if eventbrite has no tests).

- [ ] **Step 15.3: Commit**

```
git add backend/app/ingestion/eventbrite.py
git commit -m "feat(ingestion): eventbrite uses ProgressReporter + WarningCollector"
```

---

## Task 16: Refactor `dedup.py` — drop internal info line

Scheduler emits `stage.dedup` (Task 8). Remove the duplicate `logger.info(...)` at the end of `dedup_events`.

**Files:**
- Modify: `backend/app/ingestion/dedup.py`

- [ ] **Step 16.1: Delete the `logger.info` at the end of `dedup_events`**

In `backend/app/ingestion/dedup.py`, delete lines 180-185:

```python
    logger.info(
        "dedup_events: groups=%d merged=%d saved_migrated=%d",
        report.groups_found,
        report.rows_merged,
        report.saved_events_migrated,
    )
```

The function keeps `session.flush()` and `return report` unchanged.

- [ ] **Step 16.2: Run tests**

```
cd backend
pytest tests/ingestion -v -k dedup
```

Expected: PASS. Any test that asserted on the `dedup_events: groups=...` log line needs its assertion updated to check the returned `DedupReport` instead.

- [ ] **Step 16.3: Commit**

```
git add backend/app/ingestion/dedup.py
git commit -m "feat(ingestion): drop internal dedup log (scheduler emits stage.dedup)"
```

---

## Task 17: Integration test — scheduler emits the expected vocabulary

End-to-end assertion that scheduler + two fake adapters produce the full expected line sequence. This is the "did I break the vocabulary" guardrail.

**Files:**
- Create: `backend/tests/ingestion/test_scheduler_logging.py`

- [ ] **Step 17.1: Write the integration test**

Create `backend/tests/ingestion/test_scheduler_logging.py`:

```python
"""Scheduler emits the full ingestion vocabulary in order.

Guardrail against silent regressions when adapter or stage code is edited."""
import logging
from typing import Iterator

from sqlalchemy.orm import Session

from app.ingestion.categorize import CategoryDecision
from app.ingestion.logging_util import FetchContext
from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion


class _FakeAdapter:
    def __init__(self, name: str, events: list[NormalizedEvent]):
        self.name = name
        self._events = events

    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        yield from self._events


class _FakeClassifier:
    def __init__(self):
        self.stats = {"calls": 0}

    def classify(self, event: NormalizedEvent) -> CategoryDecision:
        self.stats["calls"] += 1
        return CategoryDecision(category=event.category)


def test_scheduler_emits_full_vocabulary(sqlite_session, caplog):
    """One run with two adapters should emit:
    run.start, fetch.start x2, fetch.done x2, stage.categorize,
    stage.upsert, stage.dedup, stage.embed, run.done — in that order.

    sqlite_session is the standard in-memory session fixture from conftest.
    """
    from datetime import datetime, timezone

    ev = NormalizedEvent(
        external_id="1", source="fake-a",
        title="Show", description="desc",
        start_datetime=datetime(2027, 1, 1, tzinfo=timezone.utc),
        venue_name="Venue", category="concerts", is_free=False,
        source_url="https://example.com/1",
    )
    adapters = [_FakeAdapter("fake-a", [ev]), _FakeAdapter("fake-b", [])]

    caplog.set_level(logging.INFO)
    run_ingestion(adapters=adapters, session=sqlite_session, classifier=_FakeClassifier())

    events = [getattr(r, "event", None) for r in caplog.records if getattr(r, "event", None)]
    expected_prefix = [
        "run.start",
        "fetch.start",
        "fetch.done",
        "fetch.start",
        "fetch.done",
        "stage.categorize",
        "stage.upsert",
        "stage.dedup",
        "stage.embed",
        "run.done",
    ]
    # Filter to unique-event ordering (progress lines may interleave but won't
    # occur with only 1 event).
    seen: list[str] = []
    for e in events:
        if e in {"fetch.progress", "fetch.warn", "fetch.op"}:
            continue
        seen.append(e)
    assert seen == expected_prefix, f"vocabulary drift: got {seen}"
```

- [ ] **Step 17.2: Confirm `sqlite_session` fixture exists**

The fixture is defined in `backend/tests/conftest.py` or `backend/tests/ingestion/conftest.py`. If it does not exist under that name, use whatever in-memory session fixture the existing tests use — grep for `def sqlite_session` / `def session` under `tests/`.

```
cd backend
grep -rn "def session" tests/conftest.py tests/ingestion/conftest.py
```

If the fixture is named differently, update the test to use the correct name.

- [ ] **Step 17.3: Run the test**

```
cd backend
pytest tests/ingestion/test_scheduler_logging.py -v
```

Expected: PASS.

- [ ] **Step 17.4: Run the entire ingestion test suite**

```
cd backend
pytest tests/ingestion -v
```

Expected: ALL PASS. This is the final safety net — a green run here means the vocabulary is in place across every adapter.

- [ ] **Step 17.5: Commit**

```
git add backend/tests/ingestion/test_scheduler_logging.py
git commit -m "test(ingestion): scheduler emits full vocabulary in order"
```

---

## Self-Review Notes

- **Spec coverage:** All spec sections have tasks — format & vocabulary (Tasks 1, 8), helpers (Tasks 2-5), Eventim `op`-warnings (Task 14), category `.stats` (Task 9), migration order (Tasks 10-16), test coverage (Tasks 1-5, 17).
- **Type consistency:** `FetchContext` is `ProgressReporter | NullProgress` + `WarningCollector | NullWarns` in every task. `warns.warn(cat, detail, exc=None)` signature is used everywhere. `warns.op(msg, **fields)` signature is used everywhere.
- **Placeholder scan:** No TBDs. Every code block is complete. Tests supply concrete expected values.
- **Post-migration cleanup:** Old `logger.info` / `logger.warning` calls that are superseded by the vocabulary are explicitly deleted in each adapter task; the `dedup_events` info line in Task 16.
