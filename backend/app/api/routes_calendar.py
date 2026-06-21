import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Event, SavedEvent
from app.schemas.calendar import CalendarEntry, CalendarResponse
from app.schemas.common import EventCard

router = APIRouter(prefix="/calendar", tags=["calendar"])


class SaveRequest(BaseModel):
    event_id: str


def _event_to_card(e: Event) -> EventCard:
    return EventCard(
        id=e.id, title=e.title, summary=e.summary,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
    )


@router.get("", response_model=CalendarResponse)
def get_calendar(db: DbSession) -> CalendarResponse:
    user_id = get_current_user_id()
    rows = (
        db.query(SavedEvent, Event)
        .join(Event, Event.id == SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id)
        .order_by(Event.start_datetime.asc())
        .all()
    )
    entries = [
        CalendarEntry(id=s.id, event=_event_to_card(e), saved_at=s.saved_at, kind=s.kind)
        for s, e in rows
    ]
    return CalendarResponse(entries=entries)


@router.post("", response_model=CalendarEntry)
def save_to_calendar(payload: SaveRequest, db: DbSession) -> CalendarEntry:
    user_id = get_current_user_id()
    e = db.query(Event).filter_by(id=payload.event_id).one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="event not found")
    existing = db.query(SavedEvent).filter_by(user_id=user_id, event_id=payload.event_id).one_or_none()
    if existing is None:
        existing = SavedEvent(id=str(uuid.uuid4()), user_id=user_id, event_id=payload.event_id)
        db.add(existing)
        db.commit()
        db.refresh(existing)
    return CalendarEntry(
        id=existing.id, event=_event_to_card(e),
        saved_at=existing.saved_at, kind=existing.kind,
    )


@router.delete("/{event_id}", status_code=204)
def unsave(event_id: str, db: DbSession) -> Response:
    user_id = get_current_user_id()
    row = db.query(SavedEvent).filter_by(user_id=user_id, event_id=event_id).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204)
