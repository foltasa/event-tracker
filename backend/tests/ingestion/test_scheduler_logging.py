"""Scheduler emits the full ingestion vocabulary in order.

Guardrail against silent regressions when adapter or stage code is edited."""
import logging
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.orm import Session

from app.ingestion.categorize import CategoryDecision
from app.ingestion.logging_util import FetchContext
from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion


class _FakeAdapter:
    def __init__(self, name: str, events: list[NormalizedEvent]):
        self.name = name
        self._events = events

    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        yield from self._events


class _FakeClassifier:
    def __init__(self) -> None:
        self.stats = {"calls": 0}

    def classify(self, event: NormalizedEvent) -> CategoryDecision:
        self.stats["calls"] += 1
        return CategoryDecision(category=event.category)


def test_scheduler_emits_full_vocabulary_in_order(db_session, caplog):
    ev = NormalizedEvent(
        external_id="1", source="fake-a",
        title="Show", description="desc",
        start_datetime=datetime(2027, 1, 1, tzinfo=timezone.utc),
        venue_name="Venue", category="concerts", is_free=False,
        source_url="https://example.com/1",
    )
    adapters = [_FakeAdapter("fake-a", [ev]), _FakeAdapter("fake-b", [])]

    caplog.set_level(logging.INFO)
    run_ingestion(adapters=adapters, session=db_session, classifier=_FakeClassifier())

    events = [
        getattr(r, "event", None)
        for r in caplog.records
        if getattr(r, "event", None)
    ]
    # Drop mid-flight events (progress heartbeat, aggregate warnings, op signals)
    # that may interleave — we only care about the run/fetch-per-adapter/stage
    # ordering, which is the vocabulary guardrail.
    seen = [
        e for e in events
        if e not in {"fetch.progress", "fetch.warn", "fetch.op", "stage.batch_dedup"}
    ]

    expected = [
        "run.start",
        "fetch.start",
        "fetch.done",
        "fetch.start",
        "fetch.done",
        "stage.categorize",
        "stage.upsert",
        "stage.dedup",
        "stage.embed",
        "run.done",
    ]
    assert seen == expected, f"vocabulary drift: got {seen}"
