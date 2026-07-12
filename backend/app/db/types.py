"""Custom SQLAlchemy column types."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime column with dialect-agnostic UTC semantics.

    On write: any tz-aware datetime is converted to UTC before hitting the
    driver. Naive datetimes are rejected — every producer in this codebase
    already ships tz-aware, and stopping a silent write is the whole point of
    this type. (SQLAlchemy on SQLite silently strips tzinfo without converting
    to UTC — that mismatch is what caused hour drift in the calendar for
    Berlin-shipping adapters like eventim and ohschonhell.)

    On read: attaches UTC tzinfo when the dialect returns naive (SQLite path).
    PostgreSQL's TIMESTAMPTZ already returns aware and this is a no-op.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("timezone", True)
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime passed to UTCDateTime column; producers must "
                "attach tzinfo before hitting the DB"
            )
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
