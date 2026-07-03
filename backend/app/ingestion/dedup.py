"""Post-ingest deduplication across event sources.

Groups active events by (normalized venue, +-60min start_datetime, title-Jaccard >= 0.5),
picks the highest _SOURCE_PRIORITY winner, migrates saved_events FKs, deletes losers.
Idempotent -- a second run finds no cross-source clusters."""
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.models.saved_event import SavedEvent

logger = logging.getLogger(__name__)


_SOURCE_PRIORITY: dict[str, int] = {
    "theater_hamburg": 10,
    "hamburg_scraper": 0,
    "ticketmaster": 0,
}

_TIME_TOLERANCE_MINUTES = 60
_TITLE_JACCARD_MIN = 0.5


def _normalize_venue(name: str | None) -> str:
    """Casefold, strip parenthesized hall suffix, split CamelCase, collapse whitespace."""
    if not name:
        return ""
    # Strip trailing " (Anything)" suffix (hall / room designations).
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Insert space before uppercase runs so "DeutschesSchauSpielHaus" -> "Deutsches Schau Spiel Haus".
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stripped)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    # Collapse any whitespace to single spaces.
    collapsed = re.sub(r"\s+", " ", spaced).strip().lower()
    return collapsed


def _title_jaccard(a: str | None, b: str | None) -> float:
    """Token-set Jaccard on lower-cased, punctuation-stripped titles."""
    def tokens(s: str | None) -> set[str]:
        if not s:
            return set()
        cleaned = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE).lower()
        return {t for t in cleaned.split() if t}

    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    inter = ta & tb
    return len(inter) / len(union)


@dataclass
class DedupReport:
    groups_found: int = 0
    rows_merged: int = 0
    saved_events_migrated: int = 0


def _time_bucket(dt: datetime) -> int:
    """60-min bucket key from a UTC datetime."""
    epoch_minutes = int(dt.timestamp()) // 60
    return epoch_minutes // _TIME_TOLERANCE_MINUTES


def _venue_key(name: str | None) -> str:
    """Space-stripped normalized venue for matching (absorbs CamelCase-split differences)."""
    return _normalize_venue(name).replace(" ", "")


def _match(a: Event, b: Event) -> bool:
    """Two active events are the same show iff normalized venue + time + title match."""
    if _venue_key(a.venue_name) != _venue_key(b.venue_name):
        return False
    delta = abs((a.start_datetime - b.start_datetime).total_seconds()) / 60
    if delta > _TIME_TOLERANCE_MINUTES:
        return False
    if _title_jaccard(a.title, b.title) < _TITLE_JACCARD_MIN:
        return False
    return True


def _winner_key(ev: Event) -> tuple[int, float]:
    """Higher priority wins; on ties, the older row wins (stability)."""
    priority = _SOURCE_PRIORITY.get(ev.source, 0)
    # Negate timestamp so max() picks the smallest (oldest).
    return (priority, -ev.ingested_at.timestamp())


def dedup_events(session: Session) -> DedupReport:
    """Deduplicate active events across sources. Idempotent. Runs in the caller's transaction."""
    active = session.query(Event).filter(Event.is_active.is_(True)).all()

    # Coarse bucket: (normalized venue, time bucket). Compare against bucket and bucket+1
    # so the +-60min window is preserved across bucket boundaries.
    buckets: dict[tuple[str, int], list[Event]] = {}
    for ev in active:
        key = (_venue_key(ev.venue_name), _time_bucket(ev.start_datetime))
        buckets.setdefault(key, []).append(ev)

    # Union-find over matches.
    parent: dict[str, str] = {ev.id: ev.id for ev in active}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for (venue, bucket), evs in buckets.items():
        neighbours = buckets.get((venue, bucket + 1), [])
        candidates = evs + neighbours
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                if a.id == b.id:
                    continue
                if _match(a, b):
                    union(a.id, b.id)

    # Group by root.
    clusters: dict[str, list[Event]] = {}
    for ev in active:
        clusters.setdefault(find(ev.id), []).append(ev)

    report = DedupReport()
    for cluster in clusters.values():
        if len(cluster) < 2:
            continue
        report.groups_found += 1
        winner = max(cluster, key=_winner_key)
        losers = [e for e in cluster if e.id != winner.id]

        loser_ids = [e.id for e in losers]
        # Migrate saved_events FKs from losers to winner. Handle the
        # (user_id, event_id) UNIQUE constraint: if a user already saved the
        # winner AND the loser, migrating the loser's row would collide with
        # the existing winner row. Drop the loser's row in that case.
        winner_users = {
            uid
            for (uid,) in session.query(SavedEvent.user_id)
            .filter(SavedEvent.event_id == winner.id)
            .all()
        }
        loser_saves = (
            session.query(SavedEvent).filter(SavedEvent.event_id.in_(loser_ids)).all()
        )
        for save in loser_saves:
            if save.user_id in winner_users:
                session.delete(save)
            else:
                save.event_id = winner.id
                winner_users.add(save.user_id)
                report.saved_events_migrated += 1

        for loser in losers:
            session.delete(loser)
        report.rows_merged += len(losers)

    session.flush()
    logger.info(
        "dedup_events: groups=%d merged=%d saved_migrated=%d",
        report.groups_found,
        report.rows_merged,
        report.saved_events_migrated,
    )
    return report
