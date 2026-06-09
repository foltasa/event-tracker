from fastapi import APIRouter, Query

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Event, Feedback, SavedEvent
from app.schemas.common import EventWithContext
from app.schemas.events import EventsFeedResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventsFeedResponse)
def list_events(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
) -> EventsFeedResponse:
    user_id = get_current_user_id()
    q = db.query(Event).filter(Event.is_active == True)  # noqa: E712
    if category:
        q = q.filter(Event.category == category)
    total = q.count()
    rows = (
        q.order_by(Event.start_datetime.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [r.id for r in rows]
    fb_map = {
        f.event_id: f
        for f in db.query(Feedback).filter(Feedback.user_id == user_id, Feedback.event_id.in_(ids)).all()
    }
    saved_set = {
        s.event_id
        for s in db.query(SavedEvent).filter(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids)).all()
    }

    events = []
    for r in rows:
        fb = fb_map.get(r.id)
        events.append(EventWithContext(
            id=r.id, title=r.title, summary=r.summary,
            start_datetime=r.start_datetime, end_datetime=r.end_datetime,
            venue_name=r.venue_name, venue_address=r.venue_address,
            category=r.category, tags=r.tags,
            price_min=r.price_min, price_max=r.price_max,
            is_free=r.is_free, currency=r.currency,
            image_url=r.image_url, source_url=r.source_url, source=r.source,
            is_active=r.is_active,
            user_sentiment=fb.sentiment if fb else None,
            user_comment=fb.comment if fb else None,
            is_saved=r.id in saved_set,
        ))

    return EventsFeedResponse(events=events, total=total, page=page, page_size=page_size)
