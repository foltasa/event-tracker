"""Focused test for the backfill helper. The Alembic migration itself is
kept a thin wrapper around `backfill_categories(session, classifier)` so we
can test the data logic without spinning up Alembic's runner."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db.migrations.migration_0006_helpers import backfill_categories
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision

_BERLIN = ZoneInfo("Europe/Berlin")


class _FixedClassifier:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0

    def classify(self, event):
        self.calls += 1
        cat = self.mapping.get(event.title, "unknown")
        return CategoryDecision(category=cat)


def _seed_event(session, *, external_id, title, category, venue="V"):
    row = Event(
        id=external_id,
        external_id=external_id,
        source="test",
        title=title,
        start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
        venue_name=venue,
        category=category,
        tags=[],
        is_free=False,
        source_url=f"https://example.com/{external_id}",
        raw_data={},
    )
    session.add(row)
    return row


def test_backfill_updates_categories_and_writes_cache(db_session):
    _seed_event(db_session, external_id="a", title="The 27 Club", category="concerts")
    _seed_event(db_session, external_id="b", title="Concert Real", category="concerts")
    db_session.commit()

    classifier = _FixedClassifier({
        "The 27 Club": "theater",
        "Concert Real": "concerts",
    })

    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    b = db_session.query(Event).filter_by(external_id="b").one()
    assert a.category == "theater"
    assert b.category == "concerts"
    assert db_session.query(EventCategoryCache).count() == 2


def test_backfill_is_idempotent_second_run_uses_cache(db_session):
    _seed_event(db_session, external_id="a", title="The 27 Club", category="concerts")
    db_session.commit()

    classifier = _FixedClassifier({"The 27 Club": "theater"})

    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()
    assert classifier.calls == 1

    backfill_categories(db_session, classifier=classifier, model_name="m")
    db_session.commit()
    assert classifier.calls == 1  # cache hit second time


def test_backfill_llm_failure_keeps_provider_category(db_session):
    _seed_event(db_session, external_id="a", title="X", category="concerts")
    db_session.commit()

    class _Broken:
        def classify(self, event):
            raise RuntimeError("down")

    backfill_categories(db_session, classifier=_Broken(), model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    assert a.category == "concerts"
    assert db_session.query(EventCategoryCache).count() == 0
