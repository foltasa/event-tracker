"""Backfill missing description for existing Ticketmaster events via Wikipedia.

For each event where source='ticketmaster' AND description is null/empty,
inspect raw_data._embedded.attractions[].externalLinks.wiki[].url, follow
the first URL that yields a Wikipedia REST summary, and write the extract
back as the event description. Commits per row for partial progress.
Idempotent — re-running touches only rows still missing a description.

Usage from backend/:
    python -m scripts.backfill_tm_descriptions
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.session import SessionLocal
from app.ingestion.wikipedia import extract_summary, wiki_title_from_url

logger = logging.getLogger(__name__)

_WIKI_USER_AGENT = (
    "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"
)


def _wiki_urls_for(event: Event) -> list[str]:
    atts = (event.raw_data or {}).get("_embedded", {}).get("attractions") or []
    urls: list[str] = []
    for att in atts:
        for link in ((att.get("externalLinks") or {}).get("wiki")) or []:
            if isinstance(link, dict) and link.get("url"):
                urls.append(link["url"])
    return urls


def _lookup(http_client, url: str, cache: dict[str, str | None]) -> str | None:
    if url in cache:
        return cache[url]
    parsed = wiki_title_from_url(url)
    if parsed is None:
        cache[url] = None
        return None
    host, title = parsed
    api = f"https://{host}/api/rest_v1/page/summary/{title}"
    try:
        resp = http_client.get(api, headers={"User-Agent": _WIKI_USER_AGENT})
        resp.raise_for_status()
        body = resp.json()
    except Exception:
        logger.warning("wiki summary fetch failed for %s", api)
        cache[url] = None
        return None
    text = extract_summary(body)
    cache[url] = text
    return text


def _missing(session: Session) -> list[Event]:
    return (
        session.query(Event)
        .filter(Event.source == "ticketmaster")
        .filter(or_(Event.description.is_(None), Event.description == ""))
        .all()
    )


def run(session: Session, http_client) -> dict:
    rows = _missing(session)
    scanned = len(rows)
    updated = 0
    failed = 0
    cache: dict[str, str | None] = {}

    logger.info("backfill: %d TM events missing description", scanned)
    for i, row in enumerate(rows, start=1):
        desc: str | None = None
        for url in _wiki_urls_for(row):
            desc = _lookup(http_client, url, cache)
            if desc:
                break
        if desc:
            row.description = desc
            session.commit()
            updated += 1
        else:
            failed += 1
        if i % 25 == 0:
            logger.info("progress %d/%d (updated=%d)", i, scanned, updated)

    logger.info(
        "backfill complete — scanned=%d updated=%d failed=%d", scanned, updated, failed
    )
    return {"scanned": scanned, "updated": updated, "failed": failed}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        with httpx.Client(timeout=15) as http:
            report = run(session, http)
    finally:
        session.close()
    print(f"scanned={report['scanned']} updated={report['updated']} failed={report['failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
