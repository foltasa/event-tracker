import logging
import secrets
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
from app.ingestion.logging_util import (
    FetchContext,
    ProgressReporter,
    WarningCollector,
    timer,
)
from app.ingestion.normalize import (
    UpsertReport,
    deactivate_past_events,
    dedup_by_external_id,
    upsert_events,
)
from app.ingestion.scrapers.hamburg import HamburgScraper
from app.ingestion.scrapers.ohschonhell import OhschonhellScraper
from app.ingestion.scrapers.theater_hamburg import TheaterHamburgAdapter
from app.ingestion.ticketmaster import TicketmasterAdapter
from app.rag import chroma_store
from app.rag.chroma_store import EventForEmbedding
from app.rag.chroma_store import upsert_events as chroma_upsert_events


def embed_new_events(session: Session, body: dict | None = None) -> None:
    """Embed all currently-visible events into Chroma and drop stale vectors.

    Stale = a Chroma id whose event no longer passes visible_events_filter()
    (deleted, deactivated, or — when the hide toggle is on — missing a
    description). Idempotent: upsert by id, delete by id.

    If `body` is provided (used by the scheduler's stage.embed timer),
    it is populated with `upserted` and `purged` counts."""
    visible_ids = {
        row[0]
        for row in session.query(Event.id).filter(visible_events_filter()).all()
    }
    stale = list(chroma_store.all_ids() - visible_ids)
    if stale:
        chroma_store.delete_by_ids(stale)

    rows = session.query(Event).filter(visible_events_filter()).all()
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
    if payload:
        chroma_upsert_events(payload)
    if body is not None:
        body["upserted"] = len(payload)
        body["purged"] = len(stale)


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

    Emits the standard ingestion vocabulary: run.start, per-adapter
    fetch.start/fetch.done (or fetch.skipped/fetch.failed), stage.categorize,
    stage.upsert, stage.dedup, stage.embed, run.done."""
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

    run_id = secrets.token_hex(2)
    run_start = time.monotonic()
    run_logger = logging.getLogger("app.ingestion.run")
    fetch_logger = logging.getLogger("app.ingestion.fetch")
    run_logger.info(
        "",
        extra={"event": "run.start", "body": {"run": run_id, "sources": len(adapters)}},
    )

    total_events = 0
    failed_adapters: dict[str, str] = {}
    current_stage = "fetch"

    try:
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events: list = []

        for adapter in adapters:
            state = session.get(IngestionState, adapter.name)
            tripped = state is not None and state.disabled_at is not None

            if tripped:
                fetch_logger.warning(
                    "",
                    extra={
                        "event": "fetch.skipped",
                        "body": {
                            "adapter": adapter.name,
                            "reason": "breaker-tripped",
                            "since": state.disabled_at.date().isoformat(),
                        },
                    },
                )
                continue

            fetch_logger.info(
                "", extra={"event": "fetch.start", "body": {"adapter": adapter.name}}
            )
            ctx = FetchContext(
                progress=ProgressReporter(adapter.name),
                warns=WarningCollector(adapter.name),
            )
            t0 = time.monotonic()
            try:
                batch = list(adapter.fetch(session, ctx))
            except Exception as exc:
                failed_adapters[adapter.name] = type(exc).__name__
                fetch_logger.exception(
                    "",
                    extra={
                        "event": "fetch.failed",
                        "body": {
                            "adapter": adapter.name,
                            "err": type(exc).__name__,
                            "elapsed_s": time.monotonic() - t0,
                        },
                    },
                )
                continue

            counters = ctx.progress.done()
            warnings_summary = ctx.warns.summary()
            body: dict = {"adapter": adapter.name, "events": len(batch)}
            # Merge counters (page=…, events=…) but avoid double-writing events.
            counters.pop("events", None)
            body.update(counters)
            if warnings_summary:
                body["warnings"] = warnings_summary
            fetch_logger.info("", extra={"event": "fetch.done", "body": body})

            all_events.extend(batch)
            total_events += len(batch)

        # --- In-batch dedup ---
        # Collapse (source, external_id) duplicates before they reach the
        # session. Without this, autoflush=False lets duplicate INSERTs
        # queue up and blow the UNIQUE constraint at the next flush.
        all_events, batch_drops = dedup_by_external_id(all_events)
        total_events = len(all_events)
        if batch_drops:
            logging.getLogger("app.ingestion.stage").info(
                "",
                extra={
                    "event": "stage.batch_dedup",
                    "body": {"dropped": batch_drops},
                },
            )

        # --- Categorization ---
        current_stage = "categorize"
        stats = {"events": len(all_events), "cache_hits": 0, "llm_calls": 0}
        with timer("stage.categorize", body=stats):
            for ev in all_events:
                ev.category = refine_category(ev, cache, classifier)
            stats["cache_hits"] = cache.stats["hits"]
            stats["llm_calls"] = classifier.stats["calls"]

        # --- Upsert ---
        current_stage = "upsert"
        upsert_body: dict = {}
        with timer("stage.upsert", body=upsert_body):
            report = upsert_events(session, all_events)
            deactivate_past_events(session)
            upsert_body.update(
                inserted=report.inserted, updated=report.updated, skipped=report.skipped,
            )

        # --- Dedup ---
        current_stage = "dedup"
        dedup_body: dict = {}
        with timer("stage.dedup", body=dedup_body):
            dr = dedup_events(session)
            dedup_body.update(groups=dr.groups_found, merged=dr.rows_merged)

        # --- Embed ---
        current_stage = "embed"
        embed_body: dict = {}
        with timer("stage.embed", body=embed_body):
            embed_new_events(session, body=embed_body)

        if own_session:
            session.commit()

        run_done_body: dict = {
            "events": total_events,
            "elapsed_s": time.monotonic() - run_start,
        }
        if failed_adapters:
            run_done_body["failed_adapters"] = failed_adapters
        run_logger.info("", extra={"event": "run.done", "body": run_done_body})

        if failed_adapters:
            successful = [
                a.name for a in adapters if a.name not in failed_adapters
            ]
            _emit_failure_banner(run_logger, successful, failed_adapters)

        return report
    except Exception as exc:
        if own_session:
            session.rollback()
        run_logger.exception(
            "",
            extra={
                "event": "run.failed",
                "body": {
                    "stage": current_stage,
                    "err": type(exc).__name__,
                    "elapsed_s": time.monotonic() - run_start,
                },
            },
        )
        raise
    finally:
        if own_session:
            session.close()
        if own_wiki_client and wiki_client is not None:
            wiki_client.close()


def _emit_failure_banner(
    logger_: logging.Logger,
    successful: list[str],
    failed: dict[str, str],
) -> None:
    """Log a highly-visible multi-line banner listing successful and failed
    adapters. Mirrors the style of the Eventim circuit-breaker banner so
    operators recognize the shape immediately."""
    succ_str = ", ".join(successful) if successful else "(none)"
    fail_str = ", ".join(f"{name} ({err})" for name, err in failed.items())
    logger_.warning(
        "\n!! ============================================================\n"
        "!! INGESTION RUN COMPLETED WITH FAILURES\n"
        "!!   Successful: %s\n"
        "!!   Failed:     %s\n"
        "!!   Note: successful adapter data was persisted.\n"
        "!! ============================================================",
        succ_str, fail_str,
    )


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    scheduler.add_job(run_ingestion, "cron", hour=4, minute=0)
    return scheduler
