from datetime import datetime
from typing import Iterator
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion

_BERLIN = ZoneInfo("Europe/Berlin")


def _ev(slug: str = "evt_1") -> NormalizedEvent:
    return NormalizedEvent(
        external_id=slug,
        source="test",
        title="Test Event",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=_BERLIN),
        category="music",
        is_free=False,
        source_url=f"https://example.com/{slug}",
    )


class _OkAdapter:
    name = "ok"
    def fetch(self) -> Iterator[NormalizedEvent]:
        yield _ev("ok_1")


class _FailAdapter:
    name = "fail"
    def fetch(self) -> Iterator[NormalizedEvent]:
        raise RuntimeError("source down")


def test_inserts_events(db_session):
    report = run_ingestion(adapters=[_OkAdapter()], session=db_session)
    assert report.inserted == 1


def test_failing_adapter_does_not_abort_run(db_session):
    report = run_ingestion(adapters=[_FailAdapter(), _OkAdapter()], session=db_session)
    assert report.inserted == 1


def test_aggregates_across_adapters(db_session):
    class _OkAdapter2:
        name = "ok2"
        def fetch(self):
            yield _ev("ok_2")

    report = run_ingestion(adapters=[_OkAdapter(), _OkAdapter2()], session=db_session)
    assert report.inserted == 2


def test_calls_deactivate(db_session):
    with patch("app.ingestion.scheduler.deactivate_past_events") as mock_deact:
        run_ingestion(adapters=[_OkAdapter()], session=db_session)
    mock_deact.assert_called_once_with(db_session)


def test_calls_embed_stub(db_session):
    with patch("app.ingestion.scheduler.embed_new_events") as mock_embed:
        run_ingestion(adapters=[_OkAdapter()], session=db_session)
    mock_embed.assert_called_once_with(db_session)


def test_db_error_rolls_back(db_session):
    with patch("app.ingestion.scheduler.upsert_events", side_effect=RuntimeError("db down")):
        with pytest.raises(RuntimeError, match="db down"):
            run_ingestion(adapters=[_OkAdapter()], session=db_session)


def test_all_adapters_fail_returns_empty_report(db_session):
    report = run_ingestion(adapters=[_FailAdapter(), _FailAdapter()], session=db_session)
    assert report.inserted == 0
    assert report.updated == 0
    assert report.skipped == 0


def test_embed_new_events_upserts_active_events_to_chroma(monkeypatch, db_session):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from app.db.models import Event
    from app.ingestion import scheduler

    db_session.add(Event(
        id="e1", external_id="ext1", source="eventbrite", title="Jazz",
        description="d", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
        is_active=True,
    ))
    db_session.add(Event(
        id="e2", external_id="ext2", source="eventbrite", title="Old",
        description="d", category="music", source_url="http://x",
        start_datetime=datetime(2020, 1, 1, tzinfo=timezone.utc),
        is_active=False,
    ))
    db_session.commit()

    fake_upsert = MagicMock()
    monkeypatch.setattr("app.ingestion.scheduler.chroma_upsert_events", fake_upsert)

    scheduler.embed_new_events(db_session)

    fake_upsert.assert_called_once()
    payload = fake_upsert.call_args.args[0]
    assert len(payload) == 1
    assert payload[0].id == "e1"
