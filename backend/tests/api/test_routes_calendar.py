from datetime import datetime, timezone

import pytest

from app.db.models import Event, SavedEvent, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite",
        title="Jazz", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.commit()


def test_get_calendar_empty(client, setup):
    r = client.get("/calendar")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_post_calendar_saves(client, setup, db_session):
    r = client.post("/calendar", json={"event_id": "e1"})
    assert r.status_code == 200
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1


def test_post_calendar_idempotent(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    client.post("/calendar", json={"event_id": "e1"})
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1


def test_post_calendar_unknown_event_404(client, setup):
    r = client.post("/calendar", json={"event_id": "nope"})
    assert r.status_code == 404


def test_delete_calendar(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    r = client.delete("/calendar/e1")
    assert r.status_code == 204
    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 0


def test_get_calendar_returns_entries(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    r = client.get("/calendar")
    body = r.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["event"]["id"] == "e1"


def test_get_calendar_includes_kind_saved_by_default(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    body = client.get("/calendar").json()
    assert body["entries"][0]["kind"] == "saved"


def test_get_calendar_returns_recommendation_kind(client, setup, db_session):
    import uuid
    from app.db.models import SavedEvent
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="local",
                              event_id="e1", kind="recommendation"))
    db_session.commit()
    body = client.get("/calendar").json()
    assert body["entries"][0]["kind"] == "recommendation"


def test_slot_in_promotes_recommendation_to_saved(client, setup, db_session):
    import uuid
    from app.db.models import SavedEvent
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="local",
                              event_id="e1", kind="recommendation"))
    db_session.commit()
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 200
    assert r.json()["kind"] == "saved"
    fresh = db_session.query(SavedEvent).filter_by(event_id="e1").one()
    assert fresh.kind == "saved"


def test_slot_in_idempotent_on_already_saved(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})  # creates kind='saved'
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 200
    assert r.json()["kind"] == "saved"


def test_slot_in_404_when_no_row(client, setup):
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 404
