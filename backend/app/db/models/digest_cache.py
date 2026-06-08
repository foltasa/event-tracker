from datetime import date as date_cls, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DigestCache(Base):
    __tablename__ = "digest_cache"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_digest_user_date"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    date: Mapped[date_cls] = mapped_column(Date, nullable=False)
    picks: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
