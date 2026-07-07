import logging
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models.ingestion_state import IngestionState
from app.ingestion.eventim import EventimAdapter


class _RaisingClient:
    """Any HTTP call raises — proves fetch() short-circuits when tripped."""

    def get(self, url, **kwargs):
        raise AssertionError(f"unexpected HTTP call to {url}")


def _seed_tripped(session, source: str = "eventim", *,
                  reason: str = "total_403_budget_exceeded: 15",
                  runs: int = 0) -> None:
    row = IngestionState(
        source=source,
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason=reason,
        runs_while_disabled=runs,
    )
    session.add(row)
    session.flush()


def test_fetch_returns_empty_when_tripped(db_session):
    _seed_tripped(db_session)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    assert events == []


def test_banner_logged_when_tripped(db_session, caplog):
    _seed_tripped(db_session, runs=3)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        list(adapter.fetch(db_session))
    msg = "\n".join(rec.message for rec in caplog.records)
    assert "EVENTIM ADAPTER DISABLED" in msg
    assert "total_403_budget_exceeded: 15" in msg
    assert "python -m scripts.reset_adapter_lock eventim" in msg


def test_runs_while_disabled_counter_increments(db_session):
    _seed_tripped(db_session, runs=0)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    # Adapter uses its own session to persist the counter bump; patch SessionLocal
    # to hand back the test session so the write is visible.
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched.runs_while_disabled == 2


import json
from pathlib import Path

import httpx

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _search_response(products, total_pages: int, page: int) -> str:
    return json.dumps({"products": products, "page": page, "totalPages": total_pages, "totalResults": 1})


class _RoutedClient:
    def __init__(self, routes: dict[tuple[str, int], list[tuple[int, str]]]):
        self._routes = {k: list(v) for k, v in routes.items()}

    def get(self, url, *, params, **kwargs):
        cat = params["categories"]
        page = params["page"]
        seq = self._routes.get((cat, page), [(200, _search_response([], 1, page))])
        status, body = seq.pop(0) if seq else (200, _search_response([], 1, page))
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def test_trip_on_three_consecutive_page_exhaustions(db_session):
    konzert = _load("full_konzert.json")
    # Page 1: success (need it to know totalPages)
    # Pages 2, 3, 4: exhaust retries with 403 each
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=6, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(403, "")] * 4,
        ("Konzerte", 4): [(403, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert "consecutive_retry_exhaustion" in fetched.disabled_reason


def test_trip_on_all_categories_page_1_exhausted(db_session):
    # Use 503 (retriable but not 403) so we don't accidentally hit the total-403 budget first.
    routes = {
        ("Konzerte", 1): [(503, "")] * 4,
        ("Musical & Show", 1): [(503, "")] * 4,
        ("Kultur", 1): [(503, "")] * 4,
        ("Sport", 1): [(503, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert fetched.disabled_reason == "all_categories_failed_page_1"


def test_trip_on_total_403_budget_exceeded(db_session):
    konzert = _load("full_konzert.json")
    # Alternate failing pages with successful pages so the consecutive-exhaustion
    # trip never fires (consecutive resets on each success). Failing pages
    # accumulate 4x403 each; we need > 15 total, so 4 failing pages = 16 403s.
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=10, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(200, _search_response([], total_pages=10, page=3))],
        ("Konzerte", 4): [(403, "")] * 4,
        ("Konzerte", 5): [(200, _search_response([], total_pages=10, page=5))],
        ("Konzerte", 6): [(403, "")] * 4,
        ("Konzerte", 7): [(200, _search_response([], total_pages=10, page=7))],
        ("Konzerte", 8): [(403, "")] * 4,
        ("Konzerte", 9): [(200, _search_response([], total_pages=10, page=9))],
        ("Konzerte", 10): [(200, _search_response([], total_pages=10, page=10))],
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert "total_403_budget_exceeded" in fetched.disabled_reason


def test_partial_ingest_before_trip(db_session):
    konzert = _load("full_konzert.json")
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=6, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(403, "")] * 4,
        ("Konzerte", 4): [(403, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        events = list(adapter.fetch(db_session))
    assert any(e.external_id == "20925654" for e in events)


def test_mid_run_trip_banner_logged(db_session, caplog):
    routes = {("Konzerte", 1): [(503, "")] * 4,
              ("Musical & Show", 1): [(503, "")] * 4,
              ("Kultur", 1): [(503, "")] * 4,
              ("Sport", 1): [(503, "")] * 4}
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
            list(adapter.fetch(db_session))
    msg = "\n".join(rec.message for rec in caplog.records)
    assert "EVENTIM CIRCUIT BREAKER TRIPPED THIS RUN" in msg
    assert "all_categories_failed_page_1" in msg
