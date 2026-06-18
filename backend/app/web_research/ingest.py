"""Orchestrate the web-research ingest pipeline:
   extract -> validate -> map -> upsert (SQL) -> upsert (Chroma).

Errors are partitioned: structural failures (Tavily down, extraction garbage,
URL not allowed) raise ToolError. Per-event validation/origin failures are
counted as `skipped` in the report and do not stop the others.
"""
import logging
from fnmatch import fnmatch
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.agent.schemas import ToolError
from app.config import settings
from app.db.models import Event
from app.ingestion.normalize import NormalizedEvent, upsert_events
from app.rag.chroma_store import EventForEmbedding
from app.rag.chroma_store import upsert_events as chroma_upsert
from app.web_research import client, extractor
from app.web_research.schemas import map_to_normalized_event

logger = logging.getLogger(__name__)


def _allowed(url: str) -> bool:
    csv = (settings.web_search_allowed_domains or "").strip()
    if not csv:
        return True
    host = urlparse(url).hostname or ""
    patterns = [p.strip() for p in csv.split(",") if p.strip()]
    return any(fnmatch(host, p) for p in patterns)


def ingest_event_from_url(*, url: str, session: Session) -> dict:
    """Fetch a URL, extract events, upsert them, embed them.

    Returns: {ingested, updated, skipped, event_ids}.
    Raises ToolError on structural failures.

    Concurrency invariant: the SQL upsert is committed via `session.commit()`
    before this function returns. Within a single agent turn, LangGraph ReAct
    runs tools sequentially, so any subsequent call to `search_events` in the
    same turn is guaranteed to observe the freshly-ingested rows. The Chroma
    upsert that follows the SQL commit is best-effort; failures there affect
    `get_recommendations` only, not `search_events`.
    """
    if not _allowed(url):
        raise ToolError("url not allowed")

    raw_text = client.extract(url)  # may raise ToolError
    extracted_list = extractor.extract_events(text=raw_text, source_url=url)  # may raise ToolError

    if not extracted_list:
        return {"ingested": 0, "updated": 0, "skipped": 0, "event_ids": []}

    mapped: list[NormalizedEvent] = []
    skipped_origin = 0
    for item in extracted_list:
        normed = map_to_normalized_event(item, input_url=url)
        if normed is None:
            skipped_origin += 1
            logger.info("ingest_skip_origin_mismatch url=%s extracted_url=%s", url, item.source_url)
            continue
        mapped.append(normed)

    if not mapped:
        return {"ingested": 0, "updated": 0, "skipped": skipped_origin, "event_ids": []}

    report = upsert_events(session, mapped)
    session.commit()

    # Re-query the rows to get assigned ids and embed
    keys = [e.external_id for e in mapped]
    rows = (
        session.query(Event)
        .filter(Event.source == "web_search", Event.external_id.in_(keys))
        .all()
    )
    event_ids = [r.id for r in rows]
    payload = [
        EventForEmbedding(
            id=r.id,
            title=r.title,
            description=r.description,
            category=r.category,
            venue_name=r.venue_name,
            neighborhood=None,
            start_datetime=r.start_datetime,
        )
        for r in rows
    ]
    try:
        chroma_upsert(payload)
    except Exception:
        logger.exception("chroma upsert failed; SQL state already committed")

    return {
        "ingested": report.inserted,
        "updated": report.updated,
        "skipped": report.skipped + skipped_origin,
        "event_ids": event_ids,
    }
