from datetime import datetime, timezone

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
