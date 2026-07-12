import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.agent.comment_extractor import ExtractorInput, extract_and_apply
from app.agent.memory import get_current_user_id, refresh_taste_centroids
from app.api.deps import DbSession
from app.config import settings
from app.db.models import Event, Feedback
from app.db.session import SessionLocal
from app.schemas.feedback import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _extract_in_bg(user_id: str, category: str, event_ctx: dict, text: str) -> None:
    """BackgroundTask wrapper: opens its own DB session."""
    with SessionLocal() as bg_session:
        extract_and_apply(
            bg_session,
            user_id=user_id,
            input_=ExtractorInput(
                category=category,
                source_kind="feedback",
                event_context=event_ctx,
                text=text,
            ),
        )


@router.post("", response_model=FeedbackResponse)
def post_feedback(
    payload: FeedbackCreate,
    db: DbSession,
    background: BackgroundTasks,
) -> FeedbackResponse:
    user_id = get_current_user_id()
    event = db.query(Event).filter_by(id=payload.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="event not found")

    existing = db.query(Feedback).filter_by(user_id=user_id, event_id=payload.event_id).first()
    if existing:
        existing.sentiment = payload.sentiment
        existing.comment = payload.comment
        existing.updated_at = datetime.now(timezone.utc)
        fb = existing
    else:
        fb = Feedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=payload.event_id,
            sentiment=payload.sentiment,
            comment=payload.comment,
        )
        db.add(fb)

    db.commit()
    db.refresh(fb)

    # Any signal change (like/dislike, upsert) may affect the taste centroid.
    refresh_taste_centroids(db, user_id)
    db.commit()

    if payload.comment and settings.comment_extractor_enabled:
        event_ctx = {
            "title": event.title,
            "venue": event.venue_name,
            "description": event.description,
        }
        background.add_task(
            _extract_in_bg,
            user_id=user_id,
            category=event.category,
            event_ctx=event_ctx,
            text=payload.comment,
        )

    return FeedbackResponse(
        id=fb.id, event_id=fb.event_id, sentiment=fb.sentiment,
        comment=fb.comment, created_at=fb.created_at, updated_at=fb.updated_at,
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(event_id: str, db: DbSession) -> None:
    user_id = get_current_user_id()
    existing = db.query(Feedback).filter_by(user_id=user_id, event_id=event_id).first()
    if not existing:
        return  # idempotent: silent success when there's nothing to clear
    db.delete(existing)
    db.commit()
    # Deleting any feedback row (like or dislike) can shift the centroid.
    refresh_taste_centroids(db, user_id)
    db.commit()
