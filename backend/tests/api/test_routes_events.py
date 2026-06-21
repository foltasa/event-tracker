from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.db.models import Event, Feedback, SavedEvent, User


@pytest.fixture
def setup(db_session):
    # Event start times must stay in the future relative to date.today() —
    # routes_events.list_events defaults date_from to today, so any fixture
    # event scheduled in the past would be invisible to the feed.
    db_session.add(User(id="local", interest_tags=[]))
    base = datetime.combine(date.today() + timedelta(days=1), time(12, 0), tzinfo=timezone.utc)
    for i, cat in enumerate(["music", "tech", "music"]):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", category=cat, source_url="http://x",
            start_datetime=base + timedelta(days=i),
        ))
    db_session.commit()


def test_list_events_paginated(client, setup):
    r = client.get("/events?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["events"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_list_events_category_filter(client, setup):
    r = client.get("/events?category=tech")
    body = r.json()
    assert body["total"] == 1
    assert body["events"][0]["category"] == "tech"


def test_list_events_includes_user_context(client, setup, db_session):
    db_session.add(Feedback(id="f1", user_id="local", event_id="e0",
                             sentiment="like", comment="great"))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="e0"))
    db_session.commit()
    r = client.get("/events?category=music")
    events = {e["id"]: e for e in r.json()["events"]}
    assert events["e0"]["user_sentiment"] == "like"
    assert events["e0"]["user_comment"] == "great"
    assert events["e0"]["is_saved"] is True
    assert events["e2"]["is_saved"] is False


def test_event_detail_calendar_kind_null_when_not_in_calendar(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.commit()
    r = client.get("/events/evt")
    assert r.status_code == 200
    assert r.json()["calendar_kind"] is None


def test_event_detail_calendar_kind_saved(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, SavedEvent, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="evt"))
    db_session.commit()
    body = client.get("/events/evt").json()
    assert body["calendar_kind"] == "saved"
    assert body["is_saved"] is True


def test_event_detail_calendar_kind_recommendation(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, SavedEvent, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="evt", kind="recommendation"))
    db_session.commit()
    body = client.get("/events/evt").json()
    assert body["calendar_kind"] == "recommendation"
    assert body["is_saved"] is True
