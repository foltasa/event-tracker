from datetime import datetime

from app.schemas.common import Sentiment, _JsonBase


class FeedbackCreate(_JsonBase):
    event_id: str
    sentiment: Sentiment
    comment: str | None = None


class FeedbackResponse(_JsonBase):
    id: str
    event_id: str
    sentiment: Sentiment
    comment: str | None
    created_at: datetime
    updated_at: datetime
