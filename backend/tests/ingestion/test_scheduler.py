from datetime import datetime
from typing import Iterator
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision
from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion

_BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
def fake_classifier():
    """Default classifier: returns the provider hint unchanged."""
    class _Passthrough:
        def classify(self, event):
            return CategoryDecision(category=event.category)
    return _Passthrough()


def _ev(slug: str = "evt_1") -> NormalizedEvent:
    return NormalizedEvent(
        external_id=slug,
        source="test",
        title="Test Event",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=_BERLIN),
        category="concerts",
        is_free=False,
        source_url=f"https://example.com/{slug}",
    )


class _OkAdapter:
    name = "ok"
    def fetch(self, session) -> Iterator[NormalizedEvent]:
        yield _ev("ok_1")


class _FailAdapter:
    name = "fail"
    def fetch(self, session) -> Iterator[NormalizedEvent]:
        raise RuntimeError("source down")


def test_inserts_events(db_session, fake_classifier):
    report = run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)
    assert report.inserted == 1


def test_failing_adapter_does_not_abort_run(db_session, fake_classifier):
    report = run_ingestion(adapters=[_FailAdapter(), _OkAdapter()], session=db_session, classifier=fake_classifier)
    assert report.inserted == 1


def test_aggregates_across_adapters(db_session, fake_classifier):
    class _OkAdapter2:
        name = "ok2"
        def fetch(self, session):
            yield _ev("ok_2")

    report = run_ingestion(adapters=[_OkAdapter(), _OkAdapter2()], session=db_session, classifier=fake_classifier)
    assert report.inserted == 2


def test_calls_deactivate(db_session, fake_classifier):
    with patch("app.ingestion.scheduler.deactivate_past_events") as mock_deact:
        run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)
    mock_deact.assert_called_once_with(db_session)


def test_calls_embed_stub(db_session, fake_classifier):
    with patch("app.ingestion.scheduler.embed_new_events") as mock_embed:
        run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)
    mock_embed.assert_called_once_with(db_session)


def test_db_error_rolls_back(db_session, fake_classifier):
    with patch("app.ingestion.scheduler.upsert_events", side_effect=RuntimeError("db down")):
        with pytest.raises(RuntimeError, match="db down"):
            run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)


def test_all_adapters_fail_returns_empty_report(db_session, fake_classifier):
    report = run_ingestion(adapters=[_FailAdapter(), _FailAdapter()], session=db_session, classifier=fake_classifier)
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
        description="d", category="concerts", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
        is_active=True,
    ))
    db_session.add(Event(
        id="e2", external_id="ext2", source="eventbrite", title="Old",
        description="d", category="concerts", source_url="http://x",
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


def test_embed_new_events_skips_events_without_description(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.config import settings as app_settings
    from app.db.models import Event
    from app.ingestion import scheduler

    monkeypatch.setattr(app_settings, "hide_events_without_description", True)
    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="A",
              description="Real.", start_datetime=now, category="concerts",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="B",
              description=None, start_datetime=now, category="concerts",
              tags=[], source_url="https://x/b", raw_data={}),
    ])
    db_session.commit()

    upserted: list = []
    monkeypatch.setattr(scheduler, "chroma_upsert_events", lambda payload: upserted.extend(p.id for p in payload))
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", lambda: set())
    monkeypatch.setattr(scheduler.chroma_store, "delete_by_ids", lambda ids: None)

    scheduler.embed_new_events(db_session)
    assert upserted == ["with_desc"]


def test_embed_new_events_purges_no_description_from_chroma(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.config import settings as app_settings
    from app.db.models import Event
    from app.ingestion import scheduler

    monkeypatch.setattr(app_settings, "hide_events_without_description", True)
    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add(Event(
        id="no_desc", external_id="b", source="ticketmaster", title="B",
        description=None, start_datetime=now, category="concerts",
        tags=[], source_url="https://x/b", raw_data={},
    ))
    db_session.commit()

    deleted: list = []
    monkeypatch.setattr(scheduler, "chroma_upsert_events", lambda payload: None)
    monkeypatch.setattr(scheduler.chroma_store, "all_ids", lambda: {"no_desc", "gone"})
    monkeypatch.setattr(scheduler.chroma_store, "delete_by_ids", lambda ids: deleted.extend(ids))

    scheduler.embed_new_events(db_session)
    # Both "gone" (not in DB) and "no_desc" (in DB but hidden) must be purged.
    assert set(deleted) == {"no_desc", "gone"}


def test_run_ingestion_registers_theater_hamburg_adapter():
    """The default adapter list contains a TheaterHamburgAdapter."""
    from app.ingestion.scheduler import _default_adapters
    from app.ingestion.scrapers.theater_hamburg import TheaterHamburgAdapter

    adapters = _default_adapters(wiki_client=None)
    assert any(isinstance(a, TheaterHamburgAdapter) for a in adapters)


def test_run_ingestion_calls_dedup_between_deactivate_and_embed(db_session, monkeypatch, fake_classifier):
    from app.ingestion import scheduler

    call_order: list[str] = []

    def fake_deactivate(session):
        call_order.append("deactivate")
        return 0

    def fake_dedup(session):
        from app.ingestion.dedup import DedupReport
        call_order.append("dedup")
        return DedupReport()

    def fake_embed(session):
        call_order.append("embed")

    monkeypatch.setattr(scheduler, "deactivate_past_events", fake_deactivate)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", fake_embed)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self, session):
            return iter([])

    scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session, classifier=fake_classifier)
    assert call_order == ["deactivate", "dedup", "embed"]


def test_run_ingestion_propagates_dedup_error(db_session, monkeypatch, fake_classifier):
    from app.ingestion import scheduler

    def fake_dedup(session):
        raise RuntimeError("dedup blew up")

    monkeypatch.setattr(scheduler, "deactivate_past_events", lambda s: 0)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", lambda s: None)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self, session):
            return iter([])

    with pytest.raises(RuntimeError, match="dedup blew up"):
        scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session, classifier=fake_classifier)


class _FixedClassifier:
    def __init__(self, category="theater"):
        self._category = category
        self.calls = 0

    def classify(self, event):
        self.calls += 1
        return CategoryDecision(category=self._category)


def test_ingestion_overrides_category_via_llm(db_session):
    classifier = _FixedClassifier(category="theater")
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=classifier)
    db_session.commit()
    row = db_session.query(Event).filter_by(external_id="ok_1").one()
    assert row.category == "theater"
    assert classifier.calls == 1


def test_ingestion_second_run_hits_cache(db_session):
    classifier = _FixedClassifier(category="theater")
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=classifier)
    db_session.commit()
    assert classifier.calls == 1
    assert db_session.query(EventCategoryCache).count() == 1
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=classifier)
    db_session.commit()
    assert classifier.calls == 1  # cache hit


def test_ingestion_llm_failure_uses_provider_category(db_session):
    class _BrokenClassifier:
        def classify(self, event):
            raise RuntimeError("openrouter timeout")
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=_BrokenClassifier())
    db_session.commit()
    row = db_session.query(Event).filter_by(external_id="ok_1").one()
    assert row.category == "concerts"  # _OkAdapter provider hint
    assert db_session.query(EventCategoryCache).count() == 0
