"""Seed the default user's Turing College Mon-Fri appointments for Jun + Jul 2026.

Run with: `python -m scripts.seed_default_appointments` from `backend/`.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Appointment
from app.db.session import SessionLocal

_HAMBURG = ZoneInfo("Europe/Berlin")
_TITLE = "Turing College"


def _weekdays(start: date, end_inclusive: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end_inclusive:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _local_to_utc(day: date, hour: int, minute: int) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_HAMBURG)
    return local.astimezone(timezone.utc)


def seed_turing_college(db: Session, user_id: str) -> int:
    """Insert Turing College Mon-Fri 09:00-16:30 (Hamburg local) for Jun+Jul 2026.

    Returns the number of rows inserted (existing rows are skipped).
    """
    days = _weekdays(date(2026, 6, 1), date(2026, 7, 31))
    inserted = 0
    for d in days:
        existing = (
            db.query(Appointment)
            .filter_by(user_id=user_id, title=_TITLE, day=d)
            .one_or_none()
        )
        if existing is not None:
            continue
        db.add(Appointment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=_TITLE,
            day=d,
            start_at=_local_to_utc(d, 9, 0),
            end_at=_local_to_utc(d, 16, 30),
        ))
        inserted += 1
    db.commit()
    return inserted


def main() -> None:
    with SessionLocal() as db:
        n = seed_turing_college(db, user_id=settings.default_user_id)
        print(f"Inserted {n} Turing College appointments")


if __name__ == "__main__":
    main()
