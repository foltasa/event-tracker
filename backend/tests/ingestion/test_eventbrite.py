import httpx
import pytest

from app.ingestion.eventbrite import EventbriteAdapter

_EVENT_1 = {
    "id": "eb_001",
    "name": {"text": "Jazz Night at Mojo Club"},
    "description": {"text": "A jazz evening with local musicians."},
    "summary": "Intimate trio set",
    "url": "https://www.eventbrite.de/e/jazz-night-001",
    "start": {"utc": "2026-06-14T18:00:00Z"},
    "end": {"utc": "2026-06-14T21:00:00Z"},
    "is_free": False,
    "logo": {"url": "https://img.evbuc.com/img.jpg"},
    "category": {"name": "Music"},
    "venue": {
        "name": "Mojo Club",
        "address": {"localized_address_display": "Reeperbahn 1, 20359 Hamburg"},
        "latitude": "53.5497",
        "longitude": "9.9657",
    },
    "ticket_availability": {
        "minimum_ticket_price": {"major_value": "18.00"},
        "maximum_ticket_price": {"major_value": "24.00"},
    },
    "tags": [],
}

_EVENT_FREE = {
    **_EVENT_1,
    "id": "eb_002",
    "url": "https://www.eventbrite.de/e/free-event-002",
    "is_free": True,
    "ticket_availability": None,
    "category": {"name": "Arts"},
}

_PAGE_1 = {
    "events": [_EVENT_1],
    "pagination": {"has_more_items": True, "continuation": "page2token"},
}
_PAGE_2 = {
    "events": [_EVENT_FREE],
    "pagination": {"has_more_items": False, "continuation": None},
}
_EMPTY = {"events": [], "pagination": {"has_more_items": False, "continuation": None}}


class _FakeClient:
    def __init__(self, pages: list[dict]):
        self._pages = iter(pages)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return httpx.Response(200, json=next(self._pages),
                              request=httpx.Request("GET", url))


def test_fetch_maps_music_event():
    adapter = EventbriteAdapter(client=_FakeClient([_PAGE_1, _EMPTY]))
    events = list(adapter.fetch())
    assert len(events) == 1
    e = events[0]
    assert e.external_id == "eb_001"
    assert e.source == "eventbrite"
    assert e.title == "Jazz Night at Mojo Club"
    assert e.category == "music"
    assert e.is_free is False
    assert e.price_min == 18.0
    assert e.price_max == 24.0
    assert e.venue_name == "Mojo Club"
    assert e.venue_address == "Reeperbahn 1, 20359 Hamburg"
    assert abs(e.latitude - 53.5497) < 0.001
    assert e.start_datetime.tzinfo is not None


def test_fetch_paginates():
    adapter = EventbriteAdapter(client=_FakeClient([_PAGE_1, _PAGE_2]))
    events = list(adapter.fetch())
    assert len(events) == 2
    assert events[1].external_id == "eb_002"


def test_fetch_maps_free_event():
    page = {"events": [_EVENT_FREE], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert events[0].is_free is True
    assert events[0].price_min is None
    assert events[0].price_max is None


def test_fetch_maps_arts_category():
    page = {"events": [_EVENT_FREE], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert events[0].category == "arts"


def test_fetch_returns_empty_on_no_events():
    adapter = EventbriteAdapter(client=_FakeClient([_EMPTY]))
    assert list(adapter.fetch()) == []


def test_fetch_skips_malformed_event():
    bad = {"id": "eb_bad"}  # missing name, url, start
    page = {"events": [bad, _EVENT_1], "pagination": {"has_more_items": False}}
    adapter = EventbriteAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].external_id == "eb_001"
