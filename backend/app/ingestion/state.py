"""Per-source cursor for scrapers that need to remember `last_seen_lastmod`.

Both helpers operate on the caller's session without committing. Callers are
responsible for their own transaction boundary. `set_last_seen` overwrites
unconditionally — the calling adapter owns the semantics of what the
timestamp means."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.ingestion_state import IngestionState


def get_last_seen(session: Session, source: str) -> datetime | None:
    row = session.get(IngestionState, source)
    if row is None:
        return None
    ts = row.last_seen_lastmod
    # SQLite drops tzinfo on read; re-attach as UTC so callers get an aware datetime.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def set_last_seen(session: Session, source: str, ts: datetime) -> None:
    row = session.get(IngestionState, source)
    if row is None:
        row = IngestionState(source=source, last_seen_lastmod=ts)
        session.add(row)
    else:
        row.last_seen_lastmod = ts
