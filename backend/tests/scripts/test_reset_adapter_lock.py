from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models.ingestion_state import IngestionState
from scripts.reset_adapter_lock import main


def _seed_tripped(session, source: str = "eventim") -> None:
    session.add(IngestionState(
        source=source,
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="all_categories_failed_page_1",
        runs_while_disabled=5,
    ))
    session.commit()


def test_reset_clears_trip_state_with_yes_flag(db_session, capsys):
    _seed_tripped(db_session)
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim", "--yes"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is None
    assert row.disabled_reason is None
    assert row.runs_while_disabled == 0
    out = capsys.readouterr().out
    assert "eventim" in out
    assert "reset" in out.lower()


def test_reset_prints_current_state_before_clearing(db_session, capsys):
    _seed_tripped(db_session)
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        main(["eventim", "--yes"])
    out = capsys.readouterr().out
    assert "all_categories_failed_page_1" in out
    assert "2026-07-07" in out
    assert "5" in out  # runs_while_disabled


def test_reset_missing_source_exits_1(db_session, capsys):
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["nonexistent", "--yes"])
    assert exit_code == 1
    err_out = capsys.readouterr()
    assert "not found" in (err_out.out + err_out.err).lower()


def test_reset_untripped_row_is_a_noop(db_session, capsys):
    db_session.add(IngestionState(source="eventim", last_seen_lastmod=None))
    db_session.commit()
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim", "--yes"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no trip state" in out.lower() or "already" in out.lower()


def test_reset_prompts_confirmation_without_yes_flag(db_session, monkeypatch, capsys):
    _seed_tripped(db_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is None


def test_reset_declined_confirmation_leaves_state(db_session, monkeypatch):
    _seed_tripped(db_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is not None  # still tripped
