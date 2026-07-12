"""Helpers for migration 0011 — Berlin-local ⇄ UTC conversion for
naive datetime strings stored by SQLAlchemy on SQLite.

Extracted so tests can exercise the string-shift logic without needing
an Alembic runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo("Europe/Berlin")


def _localize_berlin_to_utc(raw: str | None) -> str | None:
    """Reinterpret a stored naive ISO string as Berlin wall-clock, return UTC ISO."""
    if raw is None or raw == "":
        return raw
    normalized = raw.replace(" ", "T")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        # PostgreSQL path or previously-aware storage: already UTC-anchored, leave alone.
        return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    localized = dt.replace(tzinfo=_BERLIN)
    return localized.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _utc_to_berlin_naive(raw: str | None) -> str | None:
    """Inverse: reinterpret a naive UTC ISO string as Berlin wall-clock naive."""
    if raw is None or raw == "":
        return raw
    normalized = raw.replace(" ", "T")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BERLIN).replace(tzinfo=None).isoformat(sep=" ")
