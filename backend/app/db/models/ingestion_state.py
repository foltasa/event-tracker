from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class IngestionState(Base):
    """Per-source state row.

    Two roles: (1) cursor for sitemap-delta scrapers via `last_seen_lastmod`,
    (2) circuit-breaker for adapters that guard against sustained anti-bot
    responses. Sources may use one, both, or neither. `last_seen_lastmod` is
    nullable because circuit-breaker-only sources (e.g. eventim) never set it."""

    __tablename__ = "ingestion_state"

    source = Column(String, primary_key=True)
    last_seen_lastmod = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_reason = Column(String, nullable=True)
    runs_while_disabled = Column(Integer, nullable=False, default=0, server_default="0")
