from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize import CategoryDecision
from scripts.reclassify import reclassify_all, reclassify_sample

_BERLIN = ZoneInfo("Europe/Berlin")


class _MapClassifier:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def classify(self, event):
        self.calls.append(event.title)
        return CategoryDecision(category=self.mapping.get(event.title, "unknown"))


def _seed(session, title, category):
    session.add(Event(
        id=title, external_id=title, source="test", title=title,
        start_datetime=datetime(2026, 8, 1, tzinfo=_BERLIN),
        venue_name="V", category=category, tags=[], is_free=False,
        source_url=f"https://x/{title}", raw_data={},
    ))


def test_reclassify_all_bypasses_cache(db_session):
    _seed(db_session, "The 27 Club", "concerts")
    db_session.commit()
    db_session.add(EventCategoryCache(content_hash="anyhash", category="concerts", model="m"))
    db_session.commit()

    classifier = _MapClassifier({"The 27 Club": "theater"})
    reclassify_all(db_session, classifier=classifier, model_name="m")
    db_session.commit()

    row = db_session.query(Event).filter_by(title="The 27 Club").one()
    assert row.category == "theater"
    assert "The 27 Club" in classifier.calls


def test_reclassify_sample_does_not_persist(db_session, capsys):
    _seed(db_session, "The 27 Club", "concerts")
    db_session.commit()

    classifier = _MapClassifier({"The 27 Club": "theater"})
    reclassify_sample(db_session, classifier=classifier, model_name="m", limit=10)

    row = db_session.query(Event).filter_by(title="The 27 Club").one()
    assert row.category == "concerts"  # unchanged

    captured = capsys.readouterr()
    assert "The 27 Club" in captured.out
    assert "concerts" in captured.out
    assert "theater" in captured.out
