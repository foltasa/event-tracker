from datetime import date, datetime, timezone

from app.schemas.common import EventCard
from app.schemas.digest import DigestPick, DigestResponse


def _card():
    return EventCard(
        id="e1", title="t", summary=None,
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc), end_datetime=None,
        venue_name=None, venue_address=None, category="music", tags=[],
        price_min=None, price_max=None, is_free=True, currency="EUR",
        image_url=None, source_url="https://x", source="eventbrite", is_active=True,
    )


def test_digest_pick():
    p = DigestPick(event=_card(), justification="because")
    assert p.justification == "because"


def test_digest_response():
    r = DigestResponse(
        date=date(2026, 6, 8),
        picks=[DigestPick(event=_card(), justification="b")],
        generated_at=datetime(2026, 6, 8, 7, tzinfo=timezone.utc),
        is_cached=True,
    )
    dumped = r.model_dump(mode="json")
    assert dumped["date"] == "2026-06-08"
    assert dumped["is_cached"] is True
    assert len(dumped["picks"]) == 1
