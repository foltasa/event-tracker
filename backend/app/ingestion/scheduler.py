import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.ingestion.base import SourceAdapter
from app.ingestion.eventbrite import EventbriteAdapter
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events
from app.ingestion.scrapers.hamburg import HamburgScraper
from app.ingestion.ticketmaster import TicketmasterAdapter

logger = logging.getLogger(__name__)


def embed_new_events(session: Session) -> None:
    """Stub — Chroma embedding deferred to the RAG feature."""
    logger.info("embed_new_events: deferred, skipping")


def _default_adapters() -> list[SourceAdapter]:
    return [EventbriteAdapter(), TicketmasterAdapter(), HamburgScraper()]


def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
) -> UpsertReport:
    """Fetch all sources, upsert to DB, deactivate past events."""
    if adapters is None:
        adapters = _default_adapters()

    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        all_events = []
        for adapter in adapters:
            try:
                batch = list(adapter.fetch())
                all_events.extend(batch)
                logger.info("%s: fetched %d events", adapter.name, len(batch))
            except Exception:
                logger.exception("%s: fetch failed, skipping", adapter.name)

        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        embed_new_events(session)

        if own_session:
            session.commit()

        logger.info(
            "Ingestion complete — inserted=%d updated=%d skipped=%d",
            report.inserted, report.updated, report.skipped,
        )
        return report
    except Exception:
        if own_session:
            session.rollback()
        logger.exception("run_ingestion failed, rolled back")
        raise
    finally:
        if own_session:
            session.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    scheduler.add_job(run_ingestion, "cron", hour=4, minute=0)
    return scheduler
