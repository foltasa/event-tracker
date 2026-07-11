import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _seed_event(db, ev_id="e1", cat="concerts"):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title="t", description="d",
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=[], source_url="http://e",
        raw_data={},
    )
    db.add(e)
    return e


def test_dislike_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.refresh_taste_centroids") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "dislike", "comment": None},
        )
    assert res.status_code == 200
    m.assert_called_once()


def test_save_to_calendar_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_calendar.refresh_taste_centroids") as m:
        res = client.post("/calendar", json={"event_id": "e1"})
    assert res.status_code == 200
    m.assert_called_once()


def test_calendar_delete_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()
    client.post("/calendar", json={"event_id": "e1"})

    with patch("app.api.routes_calendar.refresh_taste_centroids") as m:
        res = client.delete("/calendar/e1")
    assert res.status_code == 204
    m.assert_called_once()


def test_feedback_with_comment_schedules_extractor(client, db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "comment_extractor_enabled", True)

    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.extract_and_apply") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "like", "comment": "great punk"},
        )
    assert res.status_code == 200
    m.assert_called_once()
    kwargs = m.call_args.kwargs or {}
    inp = kwargs.get("input_") or m.call_args.args[2]
    assert inp.category == "concerts"
    assert inp.text == "great punk"


def test_feedback_without_comment_does_not_call_extractor(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.extract_and_apply") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "like", "comment": None},
        )
    assert res.status_code == 200
    m.assert_not_called()


def test_feedback_does_not_schedule_extractor_when_disabled(client, db_session, monkeypatch):
    """When comment_extractor_enabled=False the POST does not schedule the background task."""
    from app.config import settings
    from app.db.models import Event, User

    monkeypatch.setattr(settings, "comment_extractor_enabled", False)

    ev = Event(
        id="e1", external_id="e1", source="test", title="X",
        description="d", start_datetime=__import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc),
        category="concerts", tags=[], source_url="http://e", raw_data={},
    )
    db_session.add(ev)
    db_session.add(User(id="local"))
    db_session.commit()

    called = {"n": 0}

    def fake_extract_and_apply(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr("app.api.routes_feedback.extract_and_apply", fake_extract_and_apply)

    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "like", "comment": "loved it"})
    assert r.status_code == 200
    assert called["n"] == 0
