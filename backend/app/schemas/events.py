from pydantic import Field

from app.schemas.common import EventWithContext, _JsonBase


class EventsFeedResponse(_JsonBase):
    events: list[EventWithContext] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
