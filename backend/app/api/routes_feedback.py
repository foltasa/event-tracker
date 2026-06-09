import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agent.memory import get_current_user_id, refresh_taste_centroid
from app.api.deps import DbSession
from app.db.models import Event, Feedback, User
from app.schemas.feedback import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
def post_feedback(payload: FeedbackCreate, db: DbSession) -> FeedbackResponse:
    user_id = get_current_user_id()
    if not db.query(Event).filter_by(id=payload.event_id).first():
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

    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is not None:
        user.taste_summary_dirty = True
    db.commit()
    db.refresh(fb)

    if payload.sentiment == "like":
        refresh_taste_centroid(db, user_id)
        db.commit()

    return FeedbackResponse(
        id=fb.id, event_id=fb.event_id, sentiment=fb.sentiment,
        comment=fb.comment, created_at=fb.created_at, updated_at=fb.updated_at,
    )
