from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("external_id", "source", name="uq_event_external_source"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String, nullable=True)
    venue_address: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
