import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator

from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.schemas.common import EventCategory, _JsonBase


class NormalizedEvent(_JsonBase):
    """Canonical event shape produced by every source adapter."""

    external_id: str
    source: str
    title: str
    description: str | None = None
    summary: str | None = None
    start_datetime: datetime
    end_datetime: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    category: EventCategory
    tags: list[str] = Field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    is_free: bool
    currency: str = "EUR"
    image_url: str | None = None
    source_url: str
    raw_data: dict = Field(default_factory=dict)

    @field_validator("external_id", "source_url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def _must_be_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _price_consistency(self) -> "NormalizedEvent":
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise ValueError("price_min must be <= price_max")
        if self.is_free:
            for price in (self.price_min, self.price_max):
                if price is not None and price != 0:
                    raise ValueError("is_free=True requires prices to be 0 or None")
        return self


logger = logging.getLogger(__name__)

_MUTABLE_FIELDS = (
    "title", "description", "summary", "start_datetime", "end_datetime",
    "venue_name", "venue_address", "latitude", "longitude",
    "category", "tags", "price_min", "price_max", "is_free",
    "currency", "image_url", "source_url", "raw_data",
)


@dataclass
class UpsertReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def upsert_events(session: Session, events: Iterable[NormalizedEvent]) -> UpsertReport:
    """Insert or update events keyed by (external_id, source). Does not commit."""
    report = UpsertReport()
    for ev in events:
        try:
            existing = (
                session.query(Event)
                .filter_by(external_id=ev.external_id, source=ev.source)
                .one_or_none()
            )
            if existing:
                for f in _MUTABLE_FIELDS:
                    setattr(existing, f, getattr(ev, f))
                existing.updated_at = datetime.now(timezone.utc)
                report.updated += 1
            else:
                row = Event(id=str(uuid.uuid4()), **ev.model_dump())
                session.add(row)
                report.inserted += 1
        except Exception:
            logger.exception("Failed to upsert event %s/%s", ev.source, ev.external_id)
            report.skipped += 1
    return report


def deactivate_past_events(session: Session) -> int:
    """Set is_active=False for events whose start_datetime is in the past. Does not commit."""
    now = datetime.now(timezone.utc)
    return (
        session.query(Event)
        .filter(Event.start_datetime < now, Event.is_active.is_(True))
        .update({"is_active": False}, synchronize_session="fetch")
    )


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
