import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db import run_migrations
from app.db.models import Event
from app.db.session import SessionLocal
from app.ingestion.base import SourceAdapter
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events
from app.ingestion.scrapers.hamburg import HamburgScraper
from app.ingestion.ticketmaster import TicketmasterAdapter
from app.rag.chroma_store import EventForEmbedding
from app.rag.chroma_store import upsert_events as chroma_upsert_events

logger = logging.getLogger(__name__)


def embed_new_events(session: Session) -> None:
    """Embed all currently-active events into Chroma. Idempotent: upsert by id."""
    rows = session.query(Event).filter(Event.is_active == True).all()  # noqa: E712
    if not rows:
        logger.info("embed_new_events: no active events")
        return
    payload = [
        EventForEmbedding(
            id=r.id,
            title=r.title,
            description=r.description,
            category=r.category,
            venue_name=r.venue_name,
            neighborhood=None,  # not in the current schema; leave None for MVP
            start_datetime=r.start_datetime,
        )
        for r in rows
    ]
    chroma_upsert_events(payload)
    logger.info("embed_new_events: embedded %d events", len(payload))


def _default_adapters() -> list[SourceAdapter]:
    return [TicketmasterAdapter(), HamburgScraper()]


def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
) -> UpsertReport:
    """Fetch all sources, upsert to DB, deactivate past events."""
    if adapters is None:
        adapters = _default_adapters()

    own_session = session is None
    if own_session:
        run_migrations()
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
