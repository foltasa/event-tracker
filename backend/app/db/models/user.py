from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, nullable=False, default="Hamburg")
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    about_me: Mapped[str | None] = mapped_column(String, nullable=True)
    taste_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    facts_md: Mapped[str] = mapped_column(String, nullable=False, default="")
    taste_centroid: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
