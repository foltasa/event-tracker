from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class EventCategoryCache(Base):
    """LLM-classified category, keyed by content-hash of the event's semantic
    fields (title, description, venue, tags, provider-hint). Rows survive
    across ingestion runs so each unique event is classified exactly once."""

    __tablename__ = "event_category_cache"

    content_hash = Column(String, primary_key=True)
    category = Column(String, nullable=False)
    model = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
