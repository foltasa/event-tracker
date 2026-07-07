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
