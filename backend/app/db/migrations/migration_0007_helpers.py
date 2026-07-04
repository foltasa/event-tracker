"""Helpers for migration 0007 — categories-v2 cache purge + full reclassify.

Kept outside `versions/` so Alembic doesn't try to load it as a migration
script (it scans every .py file in versions/ for a `revision` variable).

Note: this helper imports `reclassify_all` from `scripts.reclassify`. That
crosses the usual app→scripts boundary, but this migration is a one-off and
duplicating the reclassify loop here would be worse. Accept the coupling."""
import logging

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from scripts.reclassify import reclassify_all

logger = logging.getLogger(__name__)

# Categories from the v1 schema that no longer exist in v2. Remapped to
# 'other' before reclassification so mid-migration reads don't crash on
# Pydantic validation (EventCard, NormalizedEvent).
_REMOVED_CATEGORIES = ("music", "tech")


def purge_and_reclassify(session: Session, classifier, model_name: str) -> None:
    """Purge the LLM cache, remap removed v1 categories to 'other', and
    reclassify every event with the given classifier.

    Ordering matters:
    1. Purge cache first — its keys reference the v1 content_hash inputs
       (which included the old provider categories) and the v1 prompt.
    2. Safety-remap so no row carries a value outside the v2 enum.
    3. Reclassify — writes fresh cache rows under post-update hashes."""
    deleted = session.query(EventCategoryCache).delete()
    logger.info("purge_and_reclassify: dropped %d cache rows", deleted)

    remapped = session.execute(
        update(Event)
        .where(Event.category.in_(_REMOVED_CATEGORIES))
        .values(category="other")
    ).rowcount
    logger.info(
        "purge_and_reclassify: remapped %d rows with removed v1 categories to 'other'",
        remapped,
    )

    reclassify_all(session, classifier=classifier, model_name=model_name)
