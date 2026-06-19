"""LangChain tools the agent calls. Each is a thin wrapper over the DB / RAG.

Tools resolve user_id via the agent.memory contextvar. They open and close
their own DB session so the agent layer does not need to thread sessions
through tool signatures.
"""
import logging
from datetime import date, datetime, time, timezone

import numpy as np
from langchain_core.tools import tool
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.agent.memory import get_current_user_id, refresh_taste_centroid
from app.agent.memory_blob import EditError, apply_edit
from app.agent.schemas import ToolError
from app.config import settings
from app.db.models import Event, Feedback, SavedEvent, User
from app.db.session import SessionLocal
from app.rag import chroma_store
from app.rag.embeddings import embed_one
from app.web_research import client as web_research_client
from app.web_research import ingest as web_research_ingest

logger = logging.getLogger(__name__)


def _session_factory() -> Session:
    return SessionLocal()


def _event_to_summary(e: Event, similarity_score: float | None = None) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "category": e.category,
        "start_datetime": e.start_datetime.isoformat(),
        "venue_name": e.venue_name,
        "is_free": e.is_free,
        "price_min": e.price_min,
        "source_url": e.source_url,
        "similarity_score": similarity_score,
    }


@tool
def search_events(
    date_from: str | None = None,
    date_to: str | None = None,
    categories: list[str] | None = None,
    text: str | None = None,
    max_price: float | None = None,
    location: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search the events catalogue.

    Args:
        date_from: ISO date (YYYY-MM-DD), inclusive lower bound on start_datetime.
            If BOTH date_from and date_to are omitted, defaults to today
            (Europe/Berlin) for a 3-day window.
        date_to: ISO date (YYYY-MM-DD), inclusive upper bound on start_datetime.
            If BOTH date_from and date_to are omitted, defaults to today+3d
            (Europe/Berlin).
        categories: limit to these category strings (e.g. ["music", "tech"]).
        text: case-insensitive substring match on title or description.
        max_price: include only events whose price_min is <= this (or is_free=True).
        location: case-insensitive substring match on venue_name.
        limit: max rows returned (default 20, hard cap 50).
    """
    session = _session_factory()
    try:
        from datetime import timedelta as _td
        from zoneinfo import ZoneInfo
        _LOCAL_TZ = ZoneInfo("Europe/Berlin")

        if date_from is None and date_to is None:
            today_local = datetime.now(_LOCAL_TZ).date()
            date_from = today_local.isoformat()
            date_to = (today_local + _td(days=3)).isoformat()

        q = session.query(Event).filter(Event.is_active == True)  # noqa: E712
        if date_from:
            q = q.filter(Event.start_datetime >= datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
        if date_to:
            q = q.filter(Event.start_datetime <= datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))
        if categories:
            q = q.filter(Event.category.in_(categories))
        if text:
            like = f"%{text.lower()}%"
            q = q.filter(or_(Event.title.ilike(like), Event.description.ilike(like)))
        if max_price is not None:
            q = q.filter(or_(Event.is_free == True, Event.price_min <= max_price))  # noqa: E712
        if location:
            q = q.filter(Event.venue_name.ilike(f"%{location}%"))

        rows = q.order_by(Event.start_datetime.asc()).limit(min(limit, 50)).all()
        return [_event_to_summary(r) for r in rows]
    finally:
        session.close()


@tool
def get_calendar(date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Return events the current user has saved to their calendar.

    Args:
        date_from: ISO date filter on start_datetime, inclusive.
        date_to: ISO date filter on start_datetime, inclusive.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        q = (
            session.query(Event)
            .join(SavedEvent, SavedEvent.event_id == Event.id)
            .filter(SavedEvent.user_id == user_id)
        )
        if date_from:
            q = q.filter(Event.start_datetime >= datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
        if date_to:
            q = q.filter(Event.start_datetime <= datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))
        rows = q.order_by(Event.start_datetime.asc()).all()
        return [_event_to_summary(r) for r in rows]
    finally:
        session.close()


@tool
def save_to_calendar(event_id: str) -> dict:
    """Save an event to the current user's calendar. Idempotent on (user, event)."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        if not session.query(Event).filter_by(id=event_id).first():
            raise ToolError("event not found")
        exists = session.query(SavedEvent).filter_by(user_id=user_id, event_id=event_id).first()
        if exists:
            return {"status": "ok", "already_saved": True}
        import uuid as _uuid
        session.add(SavedEvent(id=str(_uuid.uuid4()), user_id=user_id, event_id=event_id))
        session.commit()
        return {"status": "ok", "already_saved": False}
    finally:
        session.close()


@tool
def get_user_profile() -> dict:
    """Return the current user's interests, about-me, and distilled taste summary."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        return {
            "interest_tags": list(user.interest_tags),
            "about_me": user.about_me,
            "taste_summary": user.taste_summary,
        }
    finally:
        session.close()


@tool
def update_user_profile(
    interest_tags: list[str] | None = None,
    about_me: str | None = None,
) -> dict:
    """Update user profile fields. Any field omitted is left unchanged."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        if interest_tags is not None:
            user.interest_tags = interest_tags
        if about_me is not None:
            user.about_me = about_me
        session.commit()
        return {"status": "ok"}
    finally:
        session.close()


@tool
def edit_facts(old_string: str, new_string: str) -> dict:
    """Edit the user's facts blob (durable user-stated facts).

    Semantics:
    - old_string="" and new_string!="" appends new_string as a new line.
    - both non-empty replaces the unique occurrence of old_string.
    - old_string!="" and new_string="" removes the unique occurrence.
    - Both empty is an error (no-op).
    - old_string must match exactly once when non-empty.
    - Resulting blob must be at most 200 lines; otherwise the edit is refused.

    Returns {"status": "ok", "lines": <new line count>} on success.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        try:
            new_blob = apply_edit(
                user.facts_md or "",
                old_string,
                new_string,
                cap=200,
                label="facts_md",
            )
        except EditError as e:
            raise ToolError(str(e))
        user.facts_md = new_blob
        session.commit()
        return {"status": "ok", "lines": len(new_blob.splitlines())}
    finally:
        session.close()


@tool
def edit_taste_summary(old_string: str, new_string: str) -> dict:
    """Edit your behavioural summary (your inferred picture of the user from
    saves/feedback).

    Same semantics as edit_facts. Cap is 20 lines. Returns
    {"status": "ok", "lines": <new line count>} on success.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        try:
            new_blob = apply_edit(
                user.taste_summary or "",
                old_string,
                new_string,
                cap=20,
                label="taste_summary",
            )
        except EditError as e:
            raise ToolError(str(e))
        user.taste_summary = new_blob
        session.commit()
        return {"status": "ok", "lines": len(new_blob.splitlines())}
    finally:
        session.close()


@tool
def get_recommendations(
    date_from: str | None = None,
    date_to: str | None = None,
    n: int = 10,
) -> list[dict]:
    """Recommend events ranked by similarity to the user's taste.

    Uses the user's taste centroid (mean of liked-event embeddings) when
    available; otherwise falls back to embedding their interest tags."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")

        if user.taste_centroid is not None and len(user.taste_centroid) > 0:
            vector = list(user.taste_centroid)
        elif user.interest_tags:
            vector = embed_one(", ".join(user.interest_tags))
        else:
            return []

        where = None
        ranges = []
        if date_from:
            ranges.append({"start_time": {"$gte": int(datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc).timestamp())}})
        if date_to:
            ranges.append({"start_time": {"$lte": int(datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc).timestamp())}})
        if ranges:
            where = {"$and": ranges} if len(ranges) > 1 else ranges[0]

        try:
            hits = chroma_store.query_by_vector(vector, n=min(n, 30), where=where)
        except Exception as exc:
            logger.exception("chroma query failed")
            raise ToolError("recommendations temporarily unavailable") from exc

        if not hits:
            return []

        id_to_score = {h.event_id: h.similarity_score for h in hits}
        rows = session.query(Event).filter(Event.id.in_(id_to_score.keys())).all()
        return sorted(
            (_event_to_summary(r, similarity_score=id_to_score[r.id]) for r in rows),
            key=lambda d: d["similarity_score"] or 0.0,
            reverse=True,
        )
    finally:
        session.close()


@tool
def record_feedback(event_id: str, sentiment: str, comment: str | None = None) -> dict:
    """Record thumbs feedback on an event.

    Args:
        event_id: Event ID being reacted to.
        sentiment: 'like' or 'dislike'.
        comment: Optional free-text comment.
    """
    if sentiment not in ("like", "dislike"):
        raise ToolError("sentiment must be 'like' or 'dislike'")
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        if not session.query(Event).filter_by(id=event_id).first():
            raise ToolError("event not found")
        existing = session.query(Feedback).filter_by(user_id=user_id, event_id=event_id).first()
        if existing:
            existing.sentiment = sentiment
            existing.comment = comment
        else:
            import uuid as _uuid
            session.add(Feedback(
                id=str(_uuid.uuid4()),
                user_id=user_id,
                event_id=event_id,
                sentiment=sentiment,
                comment=comment,
            ))
        session.commit()
        if sentiment == "like":
            refresh_taste_centroid(session, user_id)
            session.commit()
        return {"status": "ok"}
    finally:
        session.close()


import re as _re

_SNIPPET_MAX = 160

_MD_IMAGE_RE = _re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = _re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = _re.compile(r"<[^>]+>")
_WHITESPACE_RE = _re.compile(r"\s+")


def _plain_text_snippet(s: str) -> str:
    """Strip markdown/HTML decoration and collapse whitespace, then truncate.

    Order matters: drop image refs first (they look like links with a leading `!`),
    then unwrap text-bearing links (keep the visible text, drop the URL),
    then strip any leftover HTML tags, then collapse runs of whitespace."""
    if not s:
        return ""
    s = _MD_IMAGE_RE.sub("", s)
    s = _MD_LINK_RE.sub(r"\1", s)
    s = _HTML_TAG_RE.sub("", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s[:_SNIPPET_MAX]


@tool
def web_search(query: str) -> list[dict]:
    """Search the web for events using Tavily.

    Use only as a fallback when search_events returned too few results for
    the user's filters. Returns up to 5 hits with {url, title, content}.
    `content` is a plain-text snippet (stripped of markdown/HTML, max 160
    chars) for judging URL relevance — do not paste it into your reply.

    Args:
        query: A search query string. Include the user's city and ISO date
               in the query (e.g. "Theater Hamburg 2026-06-19").
    """
    from app.agent.turn_budget import consume_web_search
    consume_web_search()
    hits = web_research_client.search(query)
    out: list[dict] = []
    for h in hits:
        content = _plain_text_snippet(h.get("content") or "")
        out.append({"url": h["url"], "title": h.get("title", ""), "content": content})
    return out


@tool
def ingest_event_from_url(url: str) -> dict:
    """Fetch the given URL, extract its events, and upsert them into the catalogue.

    Use after web_search to ingest events from a promising URL. After this
    returns, call search_events again to find the newly ingested events.

    Args:
        url: Exactly one URL from a web_search result.

    Returns: {"ingested": N, "updated": M, "skipped": K, "event_ids": [...]}.
    """
    from app.agent.turn_budget import consume_ingest
    consume_ingest()
    session = _session_factory()
    try:
        report = web_research_ingest.ingest_event_from_url(url=url, session=session)
        return report
    finally:
        session.close()


ALL_TOOLS = [
    search_events,
    get_recommendations,
    record_feedback,
    save_to_calendar,
    get_calendar,
    get_user_profile,
    update_user_profile,
    edit_facts,
    edit_taste_summary,
    web_search,
    ingest_event_from_url,
]

# Tools gated by settings.web_search_enabled. The tool functions themselves are
# kept importable (and unit-testable) regardless of the flag — the flag only
# controls whether they get registered with the agent.
_WEB_SEARCH_TOOL_NAMES = frozenset({"web_search", "ingest_event_from_url"})


def _default_enabled_tools() -> list:
    if settings.web_search_enabled:
        return ALL_TOOLS
    return [t for t in ALL_TOOLS if t.name not in _WEB_SEARCH_TOOL_NAMES]


def select_tools(enabled_names: list[str] | None = None) -> list:
    if enabled_names is None:
        return _default_enabled_tools()
    by_name = {t.name: t for t in ALL_TOOLS}
    return [by_name[n] for n in enabled_names if n in by_name]
