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

from app.agent.memory import get_current_user_id
from app.agent.schemas import ToolError
from app.db.models import Event, Feedback, SavedEvent, User
from app.db.session import SessionLocal
from app.rag import chroma_store
from app.rag.embeddings import embed_one

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
        date_to: ISO date (YYYY-MM-DD), inclusive upper bound on start_datetime.
        categories: limit to these category strings (e.g. ["music", "tech"]).
        text: case-insensitive substring match on title or description.
        max_price: include only events whose price_min is <= this (or is_free=True).
        location: case-insensitive substring match on venue_name.
        limit: max rows returned (default 20, hard cap 50).
    """
    session = _session_factory()
    try:
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
    from app.agent.memory import refresh_taste_summary
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        refresh_taste_summary(session, user_id)
        session.commit()
        session.refresh(user)
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
    """Update user profile fields. Any field omitted is left unchanged.
    Marks the taste summary dirty so it regenerates on next read."""
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
        user.taste_summary_dirty = True
        session.commit()
        return {"status": "ok"}
    finally:
        session.close()
