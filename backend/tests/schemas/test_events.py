from datetime import datetime, timezone

from app.schemas.common import EventWithContext
from app.schemas.events import EventsFeedResponse


def _ctx():
    return EventWithContext(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
        user_sentiment=None, user_comment=None, is_saved=False,
    )


def test_events_feed_response():
    r = EventsFeedResponse(events=[_ctx()], total=1, page=1, page_size=20)
    assert r.total == 1
    assert r.events[0].id == "e1"
