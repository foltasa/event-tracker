"""Memory helpers shared by the agent runtime and routes.

- ContextVar for per-request user_id (set by middleware, read by tools).
- record_message: append a row to chat_messages mirror.
- refresh_taste_centroid: recompute from 'like' feedback embeddings.
"""
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ChatMessage, Feedback, User
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
