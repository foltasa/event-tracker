"""Backfill helper for migration 0006.

Kept in a normal module (not the versioned migration file) so it can be
imported and tested without invoking Alembic. The migration script itself
is a thin wrapper that calls `backfill_categories`."""
import logging
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.ingestion.categorize import CategoryCache, content_hash
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)


class _ClassifierProtocol(Protocol):
    def classify(self, event: NormalizedEvent): ...


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Some SQLite drivers strip tzinfo on read. Re-attach UTC for naive
    datetimes so pydantic's `_must_be_aware` validator is satisfied. This
    is safe because we always store UTC-normalized values."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def event_row_to_normalized(row: Event) -> NormalizedEvent:
    """Convert a DB row to the NormalizedEvent shape the classifier expects."""
    return NormalizedEvent(
        external_id=row.external_id,
        source=row.source,
        title=row.title,
        description=row.description,
        summary=row.summary,
        start_datetime=_ensure_aware(row.start_datetime),
        end_datetime=_ensure_aware(row.end_datetime),
        venue_name=row.venue_name,
        venue_address=row.venue_address,
        latitude=row.latitude,
        longitude=row.longitude,
        category=row.category,
        tags=row.tags or [],
        price_min=row.price_min,
        price_max=row.price_max,
        is_free=row.is_free,
        currency=row.currency or "EUR",
        image_url=row.image_url,
        source_url=row.source_url,
        raw_data=row.raw_data or {},
    )


def backfill_categories(
    session: Session,
    classifier: _ClassifierProtocol,
    model_name: str,
) -> None:
    """Iterate every row in `events`, classify, update `category`, and
    populate the cache. Idempotent: existing cache entries short-circuit
    the LLM call. On classifier error, the row is left untouched and no
    cache row is written (so a rerun will retry)."""
    cache = CategoryCache(session, model_name=model_name)
    rows = session.query(Event).all()
    logger.info("backfill_categories: %d events to process", len(rows))

    for i, row in enumerate(rows):
        ev = event_row_to_normalized(row)
        hash_ = content_hash(ev)
        cached = cache.get(hash_)
        if cached is not None:
            if cached != "unknown":
                row.category = cached
            continue

        try:
            decision = classifier.classify(ev)
        except Exception:
            logger.warning("backfill: classifier failed for '%s'", row.title, exc_info=True)
            continue

        if decision.category == "unknown":
            cache.set(hash_, "unknown")
            continue

        row.category = decision.category
        # Cache under the post-update hash. `content_hash` folds in
        # `event.category` (the provider hint), so a rerun of the backfill
        # reads the already-updated row and must hit the same key to
        # short-circuit. When the category didn't change, pre- and post-hash
        # are identical — one cache entry per event either way.
        post_hash = content_hash(event_row_to_normalized(row))
        cache.set(post_hash, decision.category)

        if (i + 1) % 500 == 0:
            logger.info("backfill_categories: processed %d/%d", i + 1, len(rows))
