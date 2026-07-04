"""Focused test for the categories-v2 migration helper. The Alembic
migration itself is a thin wrapper around `purge_and_reclassify`."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.migrations.migration_0007_helpers import purge_and_reclassify
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision

_BERLIN = ZoneInfo("Europe/Berlin")


class _FixedClassifier:
    def __init__(self, mapping, default="other"):
        self.mapping = mapping
        self.default = default
        self.calls = 0

    def classify(self, event):
        self.calls += 1
        return CategoryDecision(category=self.mapping.get(event.title, self.default))


def _seed_event(session, *, external_id, title, category):
    session.add(Event(
        id=external_id, external_id=external_id, source="test", title=title,
        start_datetime=datetime(2026, 8, 1, 20, 0, tzinfo=_BERLIN),
        venue_name="V", category=category, tags=[], is_free=False,
        source_url=f"https://example.com/{external_id}", raw_data={},
    ))


def test_purge_deletes_all_cache_rows(db_session):
    """Cache is invalidated because prompt + hash inputs changed."""
    db_session.add(EventCategoryCache(content_hash="old1", category="concerts", model="m"))
    db_session.add(EventCategoryCache(content_hash="old2", category="theater", model="m"))
    db_session.commit()

    classifier = _FixedClassifier({})
    purge_and_reclassify(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    # After purge, only rows the classifier itself wrote may remain (there are no events, so zero).
    assert db_session.query(EventCategoryCache).count() == 0


def test_reclassifies_all_events(db_session):
    """Every event gets a fresh classification, regardless of pre-existing category."""
    _seed_event(db_session, external_id="a", title="The 27 Club", category="concerts")
    _seed_event(db_session, external_id="b", title="Techno Night", category="concerts")
    _seed_event(db_session, external_id="c", title="Poetry Slam", category="other")
    db_session.commit()

    classifier = _FixedClassifier({
        "The 27 Club": "theater",
        "Techno Night": "party",
        "Poetry Slam": "literature",
    })

    purge_and_reclassify(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    b = db_session.query(Event).filter_by(external_id="b").one()
    c = db_session.query(Event).filter_by(external_id="c").one()
    assert a.category == "theater"
    assert b.category == "party"
    assert c.category == "literature"
    # Cache has one entry per event
    assert db_session.query(EventCategoryCache).count() == 3


def test_llm_failure_leaves_row_alone(db_session):
    _seed_event(db_session, external_id="a", title="X", category="concerts")
    db_session.commit()

    class _Broken:
        def classify(self, event):
            raise RuntimeError("down")

    purge_and_reclassify(db_session, classifier=_Broken(), model_name="m")
    db_session.commit()

    a = db_session.query(Event).filter_by(external_id="a").one()
    assert a.category == "concerts"  # unchanged (reclassify_all pattern)
    assert db_session.query(EventCategoryCache).count() == 0


def test_purge_survives_events_that_migration_created_with_invalid_old_category(db_session):
    """The plan's 'safety remap' step is inside the helper: if an event still
    has an old v1 category ('music', 'tech'), it should be remapped to 'other'
    BEFORE classification so a mid-migration read doesn't crash on Pydantic
    validation. Verify by seeding raw SQL (bypass Pydantic) with a bogus
    category and ensuring the helper handles it."""
    from sqlalchemy import text
    db_session.execute(text("""
        INSERT INTO events (id, external_id, source, title, start_datetime,
                            venue_name, category, tags, is_free, source_url,
                            raw_data, is_active, currency, ingested_at, updated_at)
        VALUES ('x', 'x', 'test', 'Legacy Event', '2026-08-01T20:00:00+00:00',
                'V', 'music', '[]', 0, 'https://x/x', '{}', 1, 'EUR',
                '2026-07-04T00:00:00+00:00', '2026-07-04T00:00:00+00:00')
    """))
    db_session.commit()

    classifier = _FixedClassifier({"Legacy Event": "concerts"})
    purge_and_reclassify(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    row = db_session.query(Event).filter_by(external_id="x").one()
    assert row.category == "concerts"
