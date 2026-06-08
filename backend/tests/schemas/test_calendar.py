from datetime import datetime, timezone

from app.schemas.calendar import CalendarEntry, CalendarResponse
from app.schemas.common import EventCard


def _card():
    return EventCard(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
    )


def test_calendar_entry():
    ce = CalendarEntry(id="sav_1", event=_card(), saved_at=datetime(2026, 6, 7, tzinfo=timezone.utc))
    assert ce.event.id == "e1"


def test_calendar_response_default_empty():
    cr = CalendarResponse()
    assert cr.entries == []
