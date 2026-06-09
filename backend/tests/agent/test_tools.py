from datetime import datetime, timezone

import pytest

from app.agent.schemas import ToolError
from app.agent import tools
from app.db.models import Event, SavedEvent, User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def events(db_session, user):
    rows = [
        Event(
            id="e_music", external_id="m1", source="eventbrite",
            title="Jazz Night", description="Trio at Mojo",
            category="music", source_url="http://x",
            start_datetime=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc),
            venue_name="Mojo", is_free=False, price_min=10.0,
        ),
        Event(
            id="e_tech", external_id="t1", source="eventbrite",
            title="Python Meetup", description="Talks",
            category="tech", source_url="http://x",
            start_datetime=datetime(2026, 6, 12, 19, 0, tzinfo=timezone.utc),
            venue_name="Betahaus", is_free=True,
        ),
    ]
    for r in rows:
        db_session.add(r)
    db_session.commit()
    return rows


def test_search_events_by_category(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke({"categories": ["music"]})
    assert len(results) == 1
    assert results[0]["id"] == "e_music"


def test_search_events_by_text(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke({"text": "python"})
    assert {r["id"] for r in results} == {"e_tech"}


def test_search_events_date_range(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke(
        {"date_from": "2026-06-11", "date_to": "2026-06-13"}
    )
    assert {r["id"] for r in results} == {"e_tech"}


def test_get_calendar_empty(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    assert tools.get_calendar.invoke({}) == []


def test_get_calendar_returns_saved(db_session, events, monkeypatch):
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="e_music"))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    results = tools.get_calendar.invoke({})
    assert [r["id"] for r in results] == ["e_music"]
