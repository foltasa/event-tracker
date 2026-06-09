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
