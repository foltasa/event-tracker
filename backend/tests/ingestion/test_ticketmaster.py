import httpx
import pytest

from app.ingestion.ticketmaster import TicketmasterAdapter

_EVENT_1 = {
    "id": "tm_001",
    "name": "Rock Concert at Barclays",
    "url": "https://www.ticketmaster.de/event/tm_001",
    "dates": {"start": {"dateTime": "2026-06-20T19:00:00Z"}},
    "images": [
        {"url": "https://s1.ticketm.net/small.jpg", "width": 205, "height": 115},
        {"url": "https://s1.ticketm.net/large.jpg", "width": 640, "height": 360},
    ],
    "priceRanges": [{"min": 25.0, "max": 45.0, "currency": "EUR", "type": "standard"}],
    "_embedded": {
        "venues": [{
            "name": "Barclays Arena",
            "address": {"line1": "Sylvesterallee 10"},
            "city": {"name": "Hamburg"},
            "location": {"latitude": "53.5897", "longitude": "9.9016"},
        }]
    },
    "classifications": [{
        "segment": {"name": "Music"},
        "genre": {"name": "Rock"},
        "primary": True,
    }],
}

_EVENT_SPORTS = {
    **_EVENT_1,
    "id": "tm_002",
    "url": "https://www.ticketmaster.de/event/tm_002",
    "classifications": [{"segment": {"name": "Sports"}, "genre": {"name": "Football"}, "primary": True}],
    "priceRanges": [],
}

_PAGE_1 = {
    "_embedded": {"events": [_EVENT_1]},
    "page": {"totalPages": 2, "number": 0, "size": 200, "totalElements": 2},
}
_PAGE_2 = {
    "_embedded": {"events": [_EVENT_SPORTS]},
    "page": {"totalPages": 2, "number": 1, "size": 200, "totalElements": 2},
}
_EMPTY = {"page": {"totalPages": 0, "number": 0, "size": 200, "totalElements": 0}}


class _FakeClient:
    def __init__(self, list_pages: list[dict], detail_map: dict[str, dict] | None = None):
        self._list_iter = iter(list_pages)
        self._detail_map = detail_map or {}

    def get(self, url: str, **kwargs) -> httpx.Response:
        if url.endswith("/events.json"):
            data = next(self._list_iter)
        else:
            event_id = url.rsplit("/", 1)[-1].removesuffix(".json")
            data = self._detail_map.get(event_id, {})
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))


def test_fetch_maps_music_event():
    adapter = TicketmasterAdapter(client=_FakeClient([_PAGE_1, _EMPTY]))
    events = list(adapter.fetch())
    assert len(events) == 1
    e = events[0]
    assert e.external_id == "tm_001"
    assert e.source == "ticketmaster"
    assert e.title == "Rock Concert at Barclays"
    assert e.category == "music"
    assert e.price_min == 25.0
    assert e.price_max == 45.0
    assert e.venue_name == "Barclays Arena"
    assert abs(e.latitude - 53.5897) < 0.001
    assert e.start_datetime.tzinfo is not None


def test_fetch_picks_largest_image():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_1]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].image_url == "https://s1.ticketm.net/large.jpg"


def test_fetch_paginates():
    adapter = TicketmasterAdapter(client=_FakeClient([_PAGE_1, _PAGE_2]))
    events = list(adapter.fetch())
    assert len(events) == 2
    assert events[0].external_id == "tm_001"
    assert events[1].external_id == "tm_002"


def test_fetch_maps_sports_category():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_SPORTS]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].category == "sports"


def test_fetch_no_price_range_yields_none():
    adapter = TicketmasterAdapter(client=_FakeClient([
        {"_embedded": {"events": [_EVENT_SPORTS]}, "page": {"totalPages": 1, "number": 0}}
    ]))
    events = list(adapter.fetch())
    assert events[0].price_min is None
    assert events[0].price_max is None
    assert events[0].is_free is False


def test_fetch_returns_empty_when_no_embedded():
    adapter = TicketmasterAdapter(client=_FakeClient([_EMPTY]))
    assert list(adapter.fetch()) == []


def test_fetch_skips_malformed_event():
    bad = {"id": "tm_bad"}
    page = {"_embedded": {"events": [bad, _EVENT_1]}, "page": {"totalPages": 1, "number": 0}}
    adapter = TicketmasterAdapter(client=_FakeClient([page]))
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].external_id == "tm_001"


def test_fetch_raises_on_http_error():
    class _ErrorClient:
        def get(self, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(429, request=httpx.Request("GET", url))

    adapter = TicketmasterAdapter(client=_ErrorClient())
    with pytest.raises(httpx.HTTPStatusError):
        list(adapter.fetch())


_DETAIL_WITH_INFO = {
    "id": "tm_001",
    "name": "Rock Concert at Barclays",
    "info": "An evening of hard rock classics.",
}

_DETAIL_WITH_ADDITIONAL = {
    "id": "tm_001",
    "additionalInfo": "Doors open at 19:00.",
}

_DETAIL_WITH_PLEASE_NOTE = {
    "id": "tm_001",
    "pleaseNote": "No re-entry after 22:00.",
}

_SINGLE_PAGE = {"_embedded": {"events": [_EVENT_1]}, "page": {"totalPages": 1, "number": 0}}


def test_description_from_detail_info():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_INFO}))
    events = list(adapter.fetch())
    assert events[0].description == "An evening of hard rock classics."


def test_description_falls_back_to_additional_info():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_ADDITIONAL}))
    events = list(adapter.fetch())
    assert events[0].description == "Doors open at 19:00."


def test_description_falls_back_to_please_note():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_PLEASE_NOTE}))
    events = list(adapter.fetch())
    assert events[0].description == "No re-entry after 22:00."


def test_description_is_none_when_detail_empty():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE]))
    events = list(adapter.fetch())
    assert events[0].description is None


def test_description_none_on_detail_http_error():
    class _ListOkDetailFail:
        def get(self, url, **kwargs):
            if url.endswith("/events.json"):
                return httpx.Response(
                    200,
                    json=_SINGLE_PAGE,
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(500, request=httpx.Request("GET", url))

    adapter = TicketmasterAdapter(client=_ListOkDetailFail())
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].description is None
