"""Uniform logging for the ingestion pipeline.

Every ingestion-related log line goes through IngestionFormatter, which
produces fixed-column output keyed on a small event vocabulary
(run.*, fetch.*, stage.*). Helpers (ProgressReporter, WarningCollector)
are added in later tasks in this same module."""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
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


def configure_logging(level: int = logging.INFO, stream=None) -> None:
    """Install IngestionFormatter on the root logger.

    Idempotent: replaces any handlers previously installed by this function
    (marked with `_ingestion_managed`). Leaves foreign handlers alone so
    pytest capture and other stacks continue to work."""
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


_progress_logger = logging.getLogger("app.ingestion.progress")


class ProgressReporter:
    """Throttled progress emitter.

    Adapters call `tick(**counters)` freely; the reporter emits `fetch.progress`
    at most once every `interval_s` seconds. The first `tick()` establishes the
    baseline and never emits (no progress yet). `done()` returns the final
    counter snapshot plus `elapsed_s` for the scheduler to fold into
    `fetch.done`."""

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
                "",
                extra={"event": "fetch.warn", "body": {**body, "detail": detail}},
                exc_info=exc_info,
            )

    def op(self, msg: str, **fields) -> None:
        body = {"adapter": self._adapter, "msg": msg, **fields}
        _warn_logger.warning("", extra={"event": "fetch.op", "body": body})

    def summary(self) -> dict[str, int]:
        return dict(self._counts)


class NullProgress:
    """No-op ProgressReporter for adapters called with ctx=None (tests, CLI)."""

    def tick(self, **counters: int) -> None: ...
    def done(self) -> dict:
        return {"elapsed_s": 0.0}


class NullWarns:
    """No-op WarningCollector for adapters called with ctx=None."""

    def warn(self, cat: str, detail: str, exc: Exception | None = None) -> None: ...
    def op(self, msg: str, **fields) -> None: ...
    def summary(self) -> dict[str, int]:
        return {}


@dataclass
class FetchContext:
    """Bundle handed to SourceAdapter.fetch by the scheduler.

    Scheduler constructs one per adapter, passes it in, then reads
    progress.done() and warns.summary() after the generator drains so
    the fetch.done line has full counters."""

    progress: "ProgressReporter | NullProgress"
    warns: "WarningCollector | NullWarns"


_stage_logger = logging.getLogger("app.ingestion.stage")


@contextmanager
def timer(event: str, body: dict, clock=time.monotonic):
    """Time a block; on exit, emit `event` with `body` + elapsed_s.

    Body is a mutable dict; callers mutate it inside the block to accumulate
    counters (cache_hits, llm_calls, etc.). The clock kwarg is for tests."""
    start = clock()
    try:
        yield body
    finally:
        body["elapsed_s"] = clock() - start
        _stage_logger.info("", extra={"event": event, "body": dict(body)})
