import json
from pathlib import Path

import httpx

from app.ingestion.eventim import EventimAdapter

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _search_response(products: list[dict], total_pages: int, page: int) -> str:
    return json.dumps({
        "products": products,
        "page": page,
        "totalPages": total_pages,
        "totalResults": total_pages * max(len(products), 1),
    })


class _FakeClient:
    """Routes: (category, page) -> (status, body). Any (cat, page) miss returns 200 empty page."""

    def __init__(self, routes: dict[tuple[str, int], tuple[int, str]] | None = None):
        self._routes = dict(routes or {})
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str, *, params: dict, **kwargs) -> httpx.Response:
        cat = params["categories"]
        page = params["page"]
        self.calls.append((cat, page))
        status, body = self._routes.get((cat, page), (200, _search_response([], 1, page)))
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def _one_of(fixture: str, overrides: dict | None = None) -> dict:
    p = _load(fixture)
    if overrides:
        p.update(overrides)
    return p


def test_happy_path_yields_events_across_all_categories(db_session):
    konzert = _one_of("full_konzert.json")
    klassik = _one_of("klassik.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=1, page=1)),
        ("Musical & Show", 1): (200, _search_response([], total_pages=1, page=1)),
        ("Kultur", 1): (200, _search_response([klassik], total_pages=1, page=1)),
        ("Sport", 1): (200, _search_response([], total_pages=1, page=1)),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    ids = sorted(e.external_id for e in events)
    assert ids == ["12345", "20925654"]


def test_paginates_full_range_per_category(db_session):
    konzert = _one_of("full_konzert.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=3, page=1)),
        ("Konzerte", 2): (200, _search_response([_one_of("full_konzert.json", {"productId": "aaa"})], total_pages=3, page=2)),
        ("Konzerte", 3): (200, _search_response([_one_of("full_konzert.json", {"productId": "bbb"})], total_pages=3, page=3)),
    }
    client = _FakeClient(routes)
    adapter = EventimAdapter(client=client, sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    konzerte_ids = sorted(e.external_id for e in events if e.raw_data.get("productId") in {"20925654", "aaa", "bbb"})
    assert konzerte_ids == ["20925654", "aaa", "bbb"]
    # Verify pages 1, 2, 3 were requested (in order) for Konzerte
    konzert_pages = [p for (c, p) in client.calls if c == "Konzerte"]
    assert konzert_pages == [1, 2, 3]


def test_mid_page_failure_is_logged_and_skipped(db_session, caplog):
    konzert_p1 = _one_of("full_konzert.json")
    konzert_p3 = _one_of("full_konzert.json", {"productId": "ccc"})
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert_p1], total_pages=3, page=1)),
        ("Konzerte", 2): (403, ""),
        ("Konzerte", 3): (200, _search_response([konzert_p3], total_pages=3, page=3)),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    ids = sorted(e.external_id for e in events)
    # Page 2 fails after retries; pages 1 and 3 still processed.
    assert "20925654" in ids
    assert "ccc" in ids


def test_sleep_between_pages(db_session):
    konzert = _one_of("full_konzert.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=2, page=1)),
        ("Konzerte", 2): (200, _search_response([_one_of("full_konzert.json", {"productId": "ddd"})], total_pages=2, page=2)),
    }
    sleeps: list[float] = []
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=sleeps.append)
    list(adapter.fetch(db_session))
    # At least one 0.2s inter-page sleep is expected.
    assert any(abs(s - 0.2) < 1e-6 for s in sleeps)


def test_query_params_are_correct(db_session):
    captured: list[dict] = []

    class _Capturing:
        def get(self, url, *, params, **kwargs):
            captured.append(dict(params))
            return httpx.Response(200, text=_search_response([], 1, params["page"]), request=httpx.Request("GET", url))

    adapter = EventimAdapter(client=_Capturing(), sleep_fn=lambda _s: None)
    list(adapter.fetch(db_session))
    p = captured[0]
    assert p["city_names"] == "Hamburg"
    assert p["webId"] == "web__eventim-de"
    assert p["language"] == "de"
    assert p["sort"] == "DateAsc"
    assert p["top"] == 50
    assert p["categories"] in {"Konzerte", "Musical & Show", "Kultur", "Sport"}


def test_all_categories_fail_page_1_trips_breaker(db_session):
    from unittest.mock import patch
    from app.db.models.ingestion_state import IngestionState
    # 503 (retriable, non-403) so we hit the all-cats trip rather than the 403 budget.
    routes = {
        ("Konzerte", 1): (503, ""),
        ("Musical & Show", 1): (503, ""),
        ("Kultur", 1): (503, ""),
        ("Sport", 1): (503, ""),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        events = list(adapter.fetch(db_session))
    assert events == []
    row = db_session.get(IngestionState, "eventim")
    assert row is not None
    assert row.disabled_at is not None
    assert row.disabled_reason == "all_categories_failed_page_1"
