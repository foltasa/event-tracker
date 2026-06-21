from datetime import date, datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Event, Feedback, SavedEvent
from app.schemas.common import EventWithContext
from app.schemas.events import EventsFeedResponse

router = APIRouter(prefix="/events", tags=["events"])


def _hydrate(e: Event, sentiment, comment, calendar_kind) -> EventWithContext:
    return EventWithContext(
        id=e.id, title=e.title, summary=e.summary,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
        user_sentiment=sentiment,
        user_comment=comment,
        is_saved=calendar_kind is not None,
        calendar_kind=calendar_kind,
    )


@router.get("", response_model=EventsFeedResponse)
def list_events(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    is_free: bool | None = None,
    q: str | None = None,
) -> EventsFeedResponse:
    user_id = get_current_user_id()
    qry = db.query(Event).filter(Event.is_active == True)  # noqa: E712
    if category:
        qry = qry.filter(Event.category == category)
    # Default lower bound to today so the upcoming feed never shows past events.
    if not date_from and not date_to:
        date_from = date.today().isoformat()
    if date_from:
        qry = qry.filter(
            Event.start_datetime
            >= datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc)
        )
    if date_to:
        qry = qry.filter(
            Event.start_datetime
            <= datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc)
        )
    if is_free is True:
        qry = qry.filter(Event.is_free == True)  # noqa: E712
    if q:
        qry = qry.filter(Event.title.ilike(f"%{q}%"))

    total = qry.count()
    rows = (
        qry.order_by(Event.start_datetime.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [r.id for r in rows]
    fb_map = {
        f.event_id: f
        for f in db.query(Feedback).filter(Feedback.user_id == user_id, Feedback.event_id.in_(ids)).all()
    }
    saved_map = {
        s.event_id: s.kind
        for s in db.query(SavedEvent).filter(
            SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids)
        ).all()
    }

    events = [
        _hydrate(
            r,
            fb_map.get(r.id).sentiment if fb_map.get(r.id) else None,
            fb_map.get(r.id).comment if fb_map.get(r.id) else None,
            saved_map.get(r.id),
        )
        for r in rows
    ]

    return EventsFeedResponse(events=events, total=total, page=page, page_size=page_size)


@router.get("/{event_id}", response_model=EventWithContext)
def get_event(event_id: str, db: DbSession) -> EventWithContext:
    user_id = get_current_user_id()
    # Do not filter on is_active: saved past events on the Calendar must still open.
    e = db.query(Event).filter(Event.id == event_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="event not found")
    fb = (
        db.query(Feedback)
        .filter(Feedback.user_id == user_id, Feedback.event_id == event_id)
        .first()
    )
    saved_row = (
        db.query(SavedEvent)
        .filter(SavedEvent.user_id == user_id, SavedEvent.event_id == event_id)
        .first()
    )
    return _hydrate(
        e,
        fb.sentiment if fb else None,
        fb.comment if fb else None,
        saved_row.kind if saved_row else None,
    )
