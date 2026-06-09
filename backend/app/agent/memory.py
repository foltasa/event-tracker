"""Memory helpers shared by the agent runtime and routes.

- ContextVar for per-request user_id (set by middleware, read by tools).
- record_message: append a row to chat_messages mirror.
- refresh_taste_summary: lazy regen when users.taste_summary_dirty.
- refresh_taste_centroid: recompute from 'like' feedback embeddings.
"""
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.agent.llm import build_llm
from app.agent.prompts import SUMMARY_PROMPT
from app.config import settings
from app.db.models import ChatMessage, Feedback, SavedEvent, User
from app.rag.chroma_store import get_embeddings_for_ids

logger = logging.getLogger(__name__)

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> str:
    return _current_user_id.get() or settings.default_user_id


def set_current_user_id(user_id: str | None) -> None:
    _current_user_id.set(user_id)


def record_message(
    session: Session,
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        tool_name=tool_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        created_at=datetime.now(timezone.utc),
    )
    session.add(msg)
    return msg


def _invoke_summary_llm(prompt: str) -> str:
    llm = build_llm(model=settings.summary_model, temperature=0.3)
    return llm.invoke(prompt).content


def refresh_taste_summary(session: Session, user_id: str) -> str | None:
    user = session.query(User).filter_by(id=user_id).one()
    if not user.taste_summary_dirty:
        return user.taste_summary

    recent_feedback = (
        session.query(Feedback)
        .filter_by(user_id=user_id)
        .order_by(Feedback.created_at.desc())
        .limit(30)
        .all()
    )
    recent_saved = (
        session.query(SavedEvent)
        .filter_by(user_id=user_id)
        .order_by(SavedEvent.saved_at.desc())
        .limit(10)
        .all()
    )

    feedback_lines = [
        f"- {f.sentiment} (event {f.event_id})" + (f": {f.comment}" if f.comment else "")
        for f in recent_feedback
    ]
    saved_lines = [f"- saved event {s.event_id}" for s in recent_saved]

    prompt = SUMMARY_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        feedback="\n".join(feedback_lines) or "(none yet)",
        saved="\n".join(saved_lines) or "(none yet)",
    )

    try:
        summary = _invoke_summary_llm(prompt).strip()
    except Exception:
        logger.exception("refresh_taste_summary: LLM failed; leaving prior summary")
        return user.taste_summary

    user.taste_summary = summary
    user.taste_summary_dirty = False
    session.flush()
    return summary


def refresh_taste_centroid(session: Session, user_id: str) -> None:
    liked = (
        session.query(Feedback)
        .filter_by(user_id=user_id, sentiment="like")
        .all()
    )
    user = session.query(User).filter_by(id=user_id).one()

    if not liked:
        user.taste_centroid = None
        session.flush()
        return

    embeddings = get_embeddings_for_ids([f.event_id for f in liked])
    if not embeddings:
        user.taste_centroid = None
        session.flush()
        return

    matrix = np.array(list(embeddings.values()), dtype=np.float32)
    centroid = matrix.mean(axis=0).tolist()
    user.taste_centroid = centroid
    session.flush()
