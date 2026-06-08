from datetime import datetime

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class CalendarEntry(_JsonBase):
    id: str
    event: EventCard
    saved_at: datetime


class CalendarResponse(_JsonBase):
    entries: list[CalendarEntry] = Field(default_factory=list)
