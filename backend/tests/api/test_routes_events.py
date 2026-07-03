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
            description=f"Description for event {i}.",
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


def test_list_events_hides_events_without_description(client, db_session):
    from app.db.models import User
    db_session.add(User(id="local", interest_tags=[]))
    future = datetime.combine(date.today() + timedelta(days=2), time(12, 0), tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="With desc",
              description="Real text.", start_datetime=future, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="No desc",
              description=None, start_datetime=future, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
        Event(id="empty_desc", external_id="c", source="ticketmaster", title="Empty desc",
              description="", start_datetime=future, category="music",
              tags=[], source_url="https://x/c", raw_data={}),
    ])
    db_session.commit()

    resp = client.get("/events")
    assert resp.status_code == 200
    data = resp.json()
    ids = {e["id"] for e in data["events"]}
    assert ids == {"with_desc"}
    assert data["total"] == 1


def test_list_events_shows_no_desc_when_toggle_off(client, db_session, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "hide_events_without_description", False)

    from app.db.models import User
    db_session.add(User(id="local", interest_tags=[]))
    future = datetime.combine(date.today() + timedelta(days=2), time(12, 0), tzinfo=timezone.utc)
    db_session.add_all([
        Event(id="with_desc", external_id="a", source="ticketmaster", title="With desc",
              description="Real text.", start_datetime=future, category="music",
              tags=[], source_url="https://x/a", raw_data={}),
        Event(id="no_desc", external_id="b", source="ticketmaster", title="No desc",
              description=None, start_datetime=future, category="music",
              tags=[], source_url="https://x/b", raw_data={}),
    ])
    db_session.commit()

    resp = client.get("/events")
    ids = {e["id"] for e in resp.json()["events"]}
    assert ids == {"with_desc", "no_desc"}


def test_get_event_returns_event_even_without_description(client, db_session):
    from app.db.models import User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(
        id="no_desc_direct", external_id="d", source="ticketmaster",
        title="Direct fetch", description=None,
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music", tags=[], source_url="https://x/d", raw_data={},
    ))
    db_session.commit()

    resp = client.get("/events/no_desc_direct")
    assert resp.status_code == 200
    assert resp.json()["id"] == "no_desc_direct"
