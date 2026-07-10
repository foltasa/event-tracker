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


def refresh_taste_centroids(session: Session, user_id: str) -> None:
    """Recompute per-category centroids and the global fallback centroid.

    Positive signals:
      like               → weight 1.0
      saved_to_calendar  → weight 2.0
    An event with both like and save gets the max (2.0), not the sum.
    Dislikes never contribute.
    """
    from app.agent.categories import CATEGORIES
    from app.db.models import Event, SavedEvent

    liked_rows = (
        session.query(Feedback.event_id, Event.category)
        .join(Event, Event.id == Feedback.event_id)
        .filter(Feedback.user_id == user_id, Feedback.sentiment == "like")
        .all()
    )
    saved_rows = (
        session.query(SavedEvent.event_id, Event.category)
        .join(Event, Event.id == SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id)
        .all()
    )

    # (event_id → (category, weight))
    per_event: dict[str, tuple[str, float]] = {}
    for eid, cat in liked_rows:
        per_event[eid] = (cat, 1.0)
    for eid, cat in saved_rows:
        # Save dominates like.
        per_event[eid] = (cat, 2.0)

    user = session.query(User).filter_by(id=user_id).one()
    if not per_event:
        user.taste_centroids = {}
        user.taste_centroid = None
        session.flush()
        return

    embeddings = get_embeddings_for_ids(list(per_event.keys()))
    if not embeddings:
        user.taste_centroids = {}
        user.taste_centroid = None
        session.flush()
        return

    # Group by category, weighted mean per group.
    per_cat_vecs: dict[str, list[np.ndarray]] = {}
    per_cat_wts: dict[str, list[float]] = {}
    for eid, (cat, w) in per_event.items():
        vec = embeddings.get(eid)
        if vec is None:
            continue
        per_cat_vecs.setdefault(cat, []).append(np.array(vec, dtype=np.float32))
        per_cat_wts.setdefault(cat, []).append(w)

    taste_centroids: dict[str, list[float]] = {}
    for cat, vecs in per_cat_vecs.items():
        weights = np.array(per_cat_wts[cat], dtype=np.float32)
        matrix = np.stack(vecs)
        weighted = np.average(matrix, axis=0, weights=weights)
        taste_centroids[cat] = weighted.tolist()

    user.taste_centroids = taste_centroids

    if taste_centroids:
        stacked = np.stack([np.array(v, dtype=np.float32) for v in taste_centroids.values()])
        user.taste_centroid = stacked.mean(axis=0).tolist()
    else:
        user.taste_centroid = None
    session.flush()


# Compatibility alias kept so old imports don't break during the migration
# transition. New code MUST call refresh_taste_centroids.
refresh_taste_centroid = refresh_taste_centroids
