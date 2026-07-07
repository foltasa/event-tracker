"""Uniform logging for the ingestion pipeline.

Every ingestion-related log line goes through IngestionFormatter, which
produces fixed-column output keyed on a small event vocabulary
(run.*, fetch.*, stage.*). Helpers (ProgressReporter, WarningCollector)
are added in later tasks in this same module."""
from __future__ import annotations

import logging
import sys
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
