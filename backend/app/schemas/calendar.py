from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class CalendarEntry(_JsonBase):
    id: str
    event: EventCard
    saved_at: datetime
    kind: Literal["saved", "recommendation"] = "saved"


class CalendarResponse(_JsonBase):
    entries: list[CalendarEntry] = Field(default_factory=list)
