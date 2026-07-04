"""Reclassification CLI.

Usage:
  python -m scripts.reclassify --all
  python -m scripts.reclassify --sample 50

`--all` bypasses the cache and re-classifies every event, updating the DB
and rewriting cache rows. Use after prompt or model changes.

`--sample N` picks N random events, classifies them, and prints a table
comparing provider hint vs LLM decision. Does NOT touch the DB. Use to
validate prompt/model tweaks before committing to a full reclassify."""
import argparse
import logging
import random

from sqlalchemy.orm import Session

from app.config import settings
from app.db.migrations.migration_0006_helpers import event_row_to_normalized
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.db.session import SessionLocal
from app.ingestion.categorize import (
    CategoryCache,
    LangchainClassifier,
    content_hash,
)

logger = logging.getLogger(__name__)


def reclassify_all(session: Session, classifier, model_name: str) -> None:
    """Bypass cache: re-classify every event and rewrite cache rows."""
    cache = CategoryCache(session, model_name=model_name)
    rows = session.query(Event).all()
    logger.info("reclassify_all: %d events", len(rows))

    for i, row in enumerate(rows):
        ev = event_row_to_normalized(row)
        try:
            decision = classifier.classify(ev)
        except Exception:
            logger.warning("reclassify: classifier failed for '%s'", row.title, exc_info=True)
            continue

        if decision.category != "unknown":
            row.category = decision.category

        # Cache under the post-update hash so subsequent backfill/ingestion
        # runs (which re-read the row) will hit the same key. Delete first
        # because CategoryCache.set uses INSERT OR IGNORE, and --all is
        # explicitly a force-refresh.
        post_hash = content_hash(event_row_to_normalized(row))
        session.query(EventCategoryCache).filter_by(content_hash=post_hash).delete()
        cache.set(post_hash, decision.category)

        if (i + 1) % 500 == 0:
            logger.info("reclassify_all: processed %d/%d", i + 1, len(rows))


def reclassify_sample(session: Session, classifier, model_name: str, limit: int) -> None:
    """Classify a random sample WITHOUT touching the DB. Prints a comparison table."""
    all_rows = session.query(Event).all()
    if not all_rows:
        print("(no events in DB)")
        return
    sample = random.sample(all_rows, min(limit, len(all_rows)))

    print(f"{'title':60} | {'provider':>10} | {'llm':>10}")
    print("-" * 90)
    for row in sample:
        ev = event_row_to_normalized(row)
        try:
            decision = classifier.classify(ev)
            llm = decision.category
        except Exception as exc:
            llm = f"ERR({type(exc).__name__})"
        print(f"{row.title[:60]:60} | {row.category:>10} | {llm:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassify events via LLM.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="re-classify every event")
    group.add_argument("--sample", type=int, metavar="N", help="dry-run N random events")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    classifier = LangchainClassifier()
    session = SessionLocal()
    try:
        if args.all:
            reclassify_all(session, classifier=classifier, model_name=settings.categorization_model)
            session.commit()
        else:
            reclassify_sample(session, classifier=classifier, model_name=settings.categorization_model, limit=args.sample)
    finally:
        session.close()


if __name__ == "__main__":
    main()
