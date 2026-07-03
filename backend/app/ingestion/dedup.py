"""Post-ingest deduplication across event sources.

Groups active events by (normalized venue, +-60min start_datetime, title-Jaccard >= 0.5),
picks the highest _SOURCE_PRIORITY winner, migrates saved_events FKs, deletes losers.
Idempotent -- a second run finds no cross-source clusters."""
import logging
import re
from dataclasses import dataclass

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
