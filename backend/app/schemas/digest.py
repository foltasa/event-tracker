from datetime import date as date_cls, datetime

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class DigestPick(_JsonBase):
    event: EventCard
    justification: str


class DigestResponse(_JsonBase):
    date: date_cls
    picks: list[DigestPick] = Field(default_factory=list)
    generated_at: datetime
    is_cached: bool
