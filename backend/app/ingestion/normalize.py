from datetime import datetime

from pydantic import Field, field_validator, model_validator

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


import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models.event import Event

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
