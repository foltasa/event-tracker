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
        def __init__(self):
            self.stats = {"calls": 0}

        def classify(self, event):
            self.stats["calls"] += 1
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
    def fetch(self, session, ctx=None) -> Iterator[NormalizedEvent]:
        yield _ev("ok_1")


class _FailAdapter:
    name = "fail"
    def fetch(self, session, ctx=None) -> Iterator[NormalizedEvent]:
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
        def fetch(self, session, ctx=None):
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
    mock_embed.assert_called_once()
    # embed_new_events(session, body=...) — first positional is the session.
    assert mock_embed.call_args.args[0] is db_session


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

    def fake_embed(session, body=None):
        call_order.append("embed")

    monkeypatch.setattr(scheduler, "deactivate_past_events", fake_deactivate)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", fake_embed)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self, session, ctx=None):
            return iter([])

    scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session, classifier=fake_classifier)
    assert call_order == ["deactivate", "dedup", "embed"]


def test_run_ingestion_propagates_dedup_error(db_session, monkeypatch, fake_classifier):
    from app.ingestion import scheduler

    def fake_dedup(session):
        raise RuntimeError("dedup blew up")

    monkeypatch.setattr(scheduler, "deactivate_past_events", lambda s: 0)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", lambda s, body=None: None)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self, session, ctx=None):
            return iter([])

    with pytest.raises(RuntimeError, match="dedup blew up"):
        scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session, classifier=fake_classifier)


class _FixedClassifier:
    def __init__(self, category="theater"):
        self._category = category
        self.calls = 0
        self.stats = {"calls": 0}

    def classify(self, event):
        self.calls += 1
        self.stats["calls"] += 1
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
        stats = {"calls": 0}
        def classify(self, event):
            self.stats["calls"] += 1
            raise RuntimeError("openrouter timeout")
    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=_BrokenClassifier())
    db_session.commit()
    row = db_session.query(Event).filter_by(external_id="ok_1").one()
    assert row.category == "concerts"  # _OkAdapter provider hint
    assert db_session.query(EventCategoryCache).count() == 0


def test_run_ingestion_emits_stage_and_adapter_logs(db_session, fake_classifier, caplog):
    """Ensures the vocabulary events fire for every stage and per adapter,
    so long runs are diagnosable from `tail -f`."""
    import logging as _logging
    caplog.set_level(_logging.INFO)

    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)

    events = [getattr(r, "event", None) for r in caplog.records if getattr(r, "event", None)]
    assert "run.start" in events
    assert "fetch.start" in events
    assert "fetch.done" in events
    assert "stage.categorize" in events
    assert "stage.upsert" in events
    assert "stage.dedup" in events
    assert "stage.embed" in events
    assert "run.done" in events

    # The fetch.done body should carry the event count for [ok].
    done = [r for r in caplog.records if getattr(r, "event", None) == "fetch.done"]
    assert any(
        r.body.get("adapter") == "ok" and r.body.get("events") == 1 for r in done
    )


class _TrippedAdapter:
    """Adapter that mimics an Eventim-style tripped-breaker no-op fetch."""
    name = "eventim"

    def fetch(self, session, ctx=None) -> Iterator[NormalizedEvent]:
        # Real adapter would log its own banner + return. We just return.
        return
        yield  # pragma: no cover


def test_scheduler_collapses_intra_batch_duplicates(db_session, fake_classifier, caplog):
    """Adapter yields the same (source, external_id) twice in one fetch.

    The scheduler must dedup in RAM before upsert so we don't crash the
    session with a UNIQUE (external_id, source) IntegrityError at flush."""
    import logging as _logging

    class _DupAdapter:
        name = "dup"

        def fetch(self, session, ctx=None):
            # Same external_id yielded twice: the adapter has an overlapping
            # category iteration bug (mimics real Eventim behaviour).
            yield NormalizedEvent(
                external_id="X", source="dup", title="First",
                start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
                category="concerts", is_free=False,
                source_url="https://example.com/dup/X",
            )
            yield NormalizedEvent(
                external_id="X", source="dup", title="Second-copy",
                start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
                category="concerts", is_free=False,
                source_url="https://example.com/dup/X",
            )

    caplog.set_level(_logging.INFO)
    report = run_ingestion(
        adapters=[_DupAdapter()], session=db_session, classifier=fake_classifier,
    )
    # Only ONE row inserted despite two yields.
    assert report.inserted == 1
    # First occurrence wins.
    stored = db_session.query(Event).filter_by(source="dup", external_id="X").one()
    assert stored.title == "First"
    # A stage.batch_dedup event was emitted with the drop count.
    dedup_events = [
        r for r in caplog.records
        if getattr(r, "event", None) == "stage.batch_dedup"
    ]
    assert len(dedup_events) == 1
    assert dedup_events[0].body == {"dropped": {"dup": 1}}


def test_scheduler_omits_batch_dedup_log_when_no_duplicates(db_session, fake_classifier, caplog):
    """When adapters are clean, no stage.batch_dedup line should appear."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier,
    )
    dedup_events = [
        r for r in caplog.records
        if getattr(r, "event", None) == "stage.batch_dedup"
    ]
    assert dedup_events == []


def test_scheduler_end_of_run_banner_lists_failed_adapters(db_session, fake_classifier, caplog):
    """Partial failure: one adapter throws, others succeed.

    Post-run.done we expect:
      - `run.done` body carries `failed_adapters={fail: RuntimeError}`.
      - A multi-line WARNING banner is logged with the successful and
        failed adapter names, right after run.done."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter(), _FailAdapter()],
        session=db_session, classifier=fake_classifier,
    )

    # run.done carries the failure map.
    run_done = [r for r in caplog.records if getattr(r, "event", None) == "run.done"]
    assert len(run_done) == 1
    assert run_done[0].body.get("failed_adapters") == {"fail": "RuntimeError"}

    # Banner appears AFTER run.done in the record stream, at WARNING level.
    all_msgs = [r.getMessage() for r in caplog.records]
    banner_indices = [
        i for i, m in enumerate(all_msgs)
        if "INGESTION RUN COMPLETED WITH FAILURES" in m
    ]
    run_done_index = next(
        i for i, r in enumerate(caplog.records)
        if getattr(r, "event", None) == "run.done"
    )
    assert len(banner_indices) == 1, "expected exactly one banner"
    assert banner_indices[0] > run_done_index
    banner = all_msgs[banner_indices[0]]
    assert "Successful: ok" in banner
    assert "Failed:     fail (RuntimeError)" in banner
    # Banner logged at WARNING so it stands out.
    assert caplog.records[banner_indices[0]].levelno == _logging.WARNING


def test_scheduler_no_banner_when_all_adapters_succeed(db_session, fake_classifier, caplog):
    """Healthy run: no banner, no failed_adapters field on run.done."""
    import logging as _logging

    caplog.set_level(_logging.INFO)
    run_ingestion(
        adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier,
    )

    run_done = [r for r in caplog.records if getattr(r, "event", None) == "run.done"]
    assert len(run_done) == 1
    assert "failed_adapters" not in run_done[0].body

    all_msgs = [r.getMessage() for r in caplog.records]
    assert not any("INGESTION RUN COMPLETED WITH FAILURES" in m for m in all_msgs)


def test_scheduler_summary_marks_tripped_adapter(db_session, fake_classifier, caplog):
    from datetime import timezone
    import logging as _logging
    from app.db.models.ingestion_state import IngestionState

    db_session.add(IngestionState(
        source="eventim",
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="all_categories_failed_page_1",
        runs_while_disabled=0,
    ))
    db_session.flush()
    with caplog.at_level(_logging.INFO):
        run_ingestion(
            adapters=[_TrippedAdapter(), _OkAdapter()],
            session=db_session,
            classifier=fake_classifier,
        )
    # New vocabulary: tripped adapter emits fetch.skipped with reason.
    skipped = [r for r in caplog.records if getattr(r, "event", None) == "fetch.skipped"]
    assert len(skipped) == 1
    assert skipped[0].body["adapter"] == "eventim"
    assert skipped[0].body["reason"] == "breaker-tripped"
