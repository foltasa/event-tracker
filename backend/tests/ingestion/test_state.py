from datetime import datetime, timezone

from app.db.models.ingestion_state import IngestionState
from app.ingestion.state import get_last_seen, set_last_seen


def test_get_last_seen_returns_none_when_absent(db_session):
    assert get_last_seen(db_session, "ohschonhell") is None


def test_set_then_get_roundtrip(db_session):
    ts = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    set_last_seen(db_session, "ohschonhell", ts)
    db_session.flush()
    got = get_last_seen(db_session, "ohschonhell")
    assert got == ts
    assert got.tzinfo is not None


def test_set_last_seen_overwrites_unconditionally(db_session):
    newer = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    older = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    set_last_seen(db_session, "ohschonhell", newer)
    db_session.flush()
    set_last_seen(db_session, "ohschonhell", older)
    db_session.flush()
    assert get_last_seen(db_session, "ohschonhell") == older


def test_set_last_seen_two_sources_independent(db_session):
    ts_a = datetime(2026, 7, 1, tzinfo=timezone.utc)
    ts_b = datetime(2026, 7, 6, tzinfo=timezone.utc)
    set_last_seen(db_session, "source_a", ts_a)
    set_last_seen(db_session, "source_b", ts_b)
    db_session.flush()
    assert get_last_seen(db_session, "source_a") == ts_a
    assert get_last_seen(db_session, "source_b") == ts_b


def test_ingestion_state_row_holds_circuit_breaker_fields(db_session):
    row = IngestionState(
        source="eventim",
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="total_403_budget_exceeded: 15",
        runs_while_disabled=3,
    )
    db_session.add(row)
    db_session.flush()
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched.disabled_at.replace(tzinfo=timezone.utc) == datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc)
    assert fetched.disabled_reason == "total_403_budget_exceeded: 15"
    assert fetched.runs_while_disabled == 3
    assert fetched.last_seen_lastmod is None
