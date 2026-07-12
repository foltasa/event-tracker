"""One-shot backfill: (re)populate Chroma from the current visible events.

Wraps `app.ingestion.scheduler.embed_new_events` in an owned DB session so
operators can run it independently of the nightly ingestion cron. Idempotent
— safe to re-run: upserts by event id and drops stale ids."""
import logging

from app.db.session import SessionLocal
from app.ingestion.scheduler import embed_new_events
from app.rag import chroma_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("embed_events")


def main() -> None:
    body: dict = {}
    with SessionLocal() as session:
        embed_new_events(session, body=body)
        session.commit()
    logger.info(
        "backfill complete: upserted=%s purged=%s total_in_chroma=%s",
        body.get("upserted"),
        body.get("purged"),
        chroma_store._get_collection().count(),
    )


if __name__ == "__main__":
    main()
