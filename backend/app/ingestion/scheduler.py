import logging
import time

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.config import settings
from app.db import run_migrations
from app.db.models import Event
from app.db.models.event import visible_events_filter
from app.db.models.ingestion_state import IngestionState
from app.db.session import SessionLocal
from app.ingestion.base import SourceAdapter
from app.ingestion.categorize import (
    CategoryCache,
    LangchainClassifier,
    LLMClassifier,
    refine_category,
)
from app.ingestion.dedup import dedup_events
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events
from app.ingestion.scrapers.hamburg import HamburgScraper
from app.ingestion.scrapers.ohschonhell import OhschonhellScraper
from app.ingestion.scrapers.theater_hamburg import TheaterHamburgAdapter
from app.ingestion.ticketmaster import TicketmasterAdapter
from app.rag import chroma_store
from app.rag.chroma_store import EventForEmbedding
from app.rag.chroma_store import upsert_events as chroma_upsert_events

logger = logging.getLogger(__name__)


def embed_new_events(session: Session) -> None:
    """Embed all currently-visible events into Chroma and drop stale vectors.

    Stale = a Chroma id whose event no longer passes visible_events_filter()
    (deleted, deactivated, or — when the hide toggle is on — missing a
    description). Idempotent: upsert by id, delete by id."""
    visible_ids = {
        row[0]
        for row in session.query(Event.id).filter(visible_events_filter()).all()
    }
    stale = list(chroma_store.all_ids() - visible_ids)
    if stale:
        chroma_store.delete_by_ids(stale)
        logger.info("embed_new_events: purged %d stale Chroma vector(s)", len(stale))

    rows = session.query(Event).filter(visible_events_filter()).all()
    if not rows:
        logger.info("embed_new_events: no visible events")
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


def _default_adapters(wiki_client: httpx.Client | None = None) -> list[SourceAdapter]:
    from app.ingestion.eventim import EventimAdapter
    return [
        TicketmasterAdapter(wiki_client=wiki_client),
        HamburgScraper(),
        TheaterHamburgAdapter(),
        OhschonhellScraper(),
        EventimAdapter(),
    ]


def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
    classifier: LLMClassifier | None = None,
) -> UpsertReport:
    """Fetch all sources, upsert to DB, deactivate past events.

    Between fetch and upsert each event is passed through `refine_category`
    so the LLM classifier (with content-hash cache) has final say over the
    provider's substring-mapped category hint."""
    own_wiki_client = adapters is None
    wiki_client = httpx.Client(timeout=15) if own_wiki_client else None
    if adapters is None:
        adapters = _default_adapters(wiki_client=wiki_client)

    own_session = session is None
    if own_session:
        run_migrations()
        session = SessionLocal()

    if classifier is None:
        classifier = LangchainClassifier()

    try:
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events = []
        per_adapter_counts: dict[str, int | None] = {}  # None = tripped/skipped
        logger.info("stage: fetch (%d sources)", len(adapters))
        for adapter in adapters:
            state = session.get(IngestionState, adapter.name)
            tripped = state is not None and state.disabled_at is not None
            logger.info("[%s] fetch starting", adapter.name)
            t0 = time.monotonic()
            try:
                batch = list(adapter.fetch(session))
                elapsed = time.monotonic() - t0
                logger.info("[%s] fetched %d events in %.1fs", adapter.name, len(batch), elapsed)
            except Exception:
                logger.exception(
                    "[%s] fetch failed after %.1fs — skipping",
                    adapter.name, time.monotonic() - t0,
                )
                per_adapter_counts[adapter.name] = None
                continue
            all_events.extend(batch)
            # If the adapter was tripped, it returned an empty batch on purpose.
            per_adapter_counts[adapter.name] = None if (tripped and not batch) else len(batch)

        logger.info("stage: categorization (%d events)", len(all_events))
        for ev in all_events:
            ev.category = refine_category(ev, cache, classifier)

        logger.info("stage: upsert")
        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        logger.info("stage: dedup")
        dedup_events(session)  # logs its own summary
        logger.info("stage: embedding")
        embed_new_events(session)

        if own_session:
            session.commit()

        # Per-adapter summary at end of run
        logger.info("ingest summary:")
        name_w = max(len(a.name) for a in adapters)
        for adapter in adapters:
            n = per_adapter_counts.get(adapter.name)
            if n is None:
                logger.info(
                    "  %-*s : *** SKIPPED - CIRCUIT BREAKER TRIPPED *** (see WARNING above)",
                    name_w, adapter.name,
                )
            else:
                logger.info("  %-*s : %d events", name_w, adapter.name, n)

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
        if own_wiki_client and wiki_client is not None:
            wiki_client.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    scheduler.add_job(run_ingestion, "cron", hour=4, minute=0)
    return scheduler
