from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class IngestionState(Base):
    """Per-source cursor used by scrapers with sitemap-delta or feed-poll
    discovery. `last_seen_lastmod` is the highest source-side modification
    timestamp the scraper has successfully processed."""

    __tablename__ = "ingestion_state"

    source = Column(String, primary_key=True)
    last_seen_lastmod = Column(DateTime(timezone=True), nullable=False)
