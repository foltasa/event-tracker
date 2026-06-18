from datetime import datetime, timezone

import pytest

from app.agent.schemas import ToolError
from app.agent import tools
from app.db.models import Event, Feedback, SavedEvent, User
from app.rag import chroma_store


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
    results = tools.search_events.invoke(
        {"categories": ["music"], "date_from": "2026-06-01", "date_to": "2026-06-30"}
    )
    assert len(results) == 1
    assert results[0]["id"] == "e_music"


def test_search_events_by_text(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    results = tools.search_events.invoke(
        {"text": "python", "date_from": "2026-06-01", "date_to": "2026-06-30"}
    )
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


def test_save_to_calendar_idempotent(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    tools.save_to_calendar.invoke({"event_id": "e_music"})
    tools.save_to_calendar.invoke({"event_id": "e_music"})  # second call must not raise
    rows = db_session.query(SavedEvent).filter_by(user_id="local", event_id="e_music").all()
    assert len(rows) == 1


def test_save_to_calendar_unknown_raises_toolerror(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    with pytest.raises(ToolError, match="event not found"):
        tools.save_to_calendar.invoke({"event_id": "nope"})


def test_get_user_profile_returns_profile(db_session, user, monkeypatch):
    user.taste_summary = "loves jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    result = tools.get_user_profile.invoke({})
    assert result == {
        "interest_tags": ["music"],
        "about_me": None,
        "taste_summary": "loves jazz",
    }


def test_update_user_profile_updates_fields(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    tools.update_user_profile.invoke({"interest_tags": ["music", "tech"], "about_me": "loves indie"})
    # Tool closes its session, which expunges instances from the shared test session.
    # Re-fetch via a fresh query instead of refresh().
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.interest_tags == ["music", "tech"]
    assert fresh.about_me == "loves indie"


def test_get_recommendations_cold_start_uses_interest_tags(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "embed_one", lambda text: [0.42] * 1536)

    captured = {}

    def fake_query(vector, n, where=None):
        captured["vector"] = vector
        captured["n"] = n
        return [
            chroma_store.QueryHit(event_id="e_music", similarity_score=0.9),
            chroma_store.QueryHit(event_id="e_tech", similarity_score=0.8),
        ]

    monkeypatch.setattr(tools.chroma_store, "query_by_vector", fake_query)

    results = tools.get_recommendations.invoke({"n": 2})
    assert len(results) == 2
    assert results[0]["id"] == "e_music"
    assert results[0]["similarity_score"] == 0.9
    assert captured["vector"] == [0.42] * 1536


def test_get_recommendations_uses_centroid_when_present(db_session, user, events, monkeypatch):
    user.taste_centroid = [0.7] * 1536
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "embed_one", lambda text: pytest.fail("must not embed when centroid set"))
    captured = {}

    def fake_query(vector, n, where=None):
        captured["vector"] = vector
        return [chroma_store.QueryHit(event_id="e_music", similarity_score=0.99)]

    monkeypatch.setattr(tools.chroma_store, "query_by_vector", fake_query)

    results = tools.get_recommendations.invoke({"n": 1})
    assert captured["vector"] == [0.7] * 1536
    assert results[0]["id"] == "e_music"


def test_record_feedback_inserts_row(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    monkeypatch.setattr(tools, "refresh_taste_centroid", lambda s, uid: None)

    tools.record_feedback.invoke({
        "event_id": "e_music", "sentiment": "like", "comment": "loved it",
    })

    row = db_session.query(Feedback).filter_by(user_id="local", event_id="e_music").one()
    assert row.sentiment == "like"
    assert row.comment == "loved it"


def test_record_feedback_like_refreshes_centroid(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    called = {"refreshed": False}

    def fake_refresh(s, uid):
        called["refreshed"] = True

    monkeypatch.setattr(tools, "refresh_taste_centroid", fake_refresh)
    tools.record_feedback.invoke({"event_id": "e_music", "sentiment": "like"})
    assert called["refreshed"] is True


def test_record_feedback_dislike_skips_centroid_refresh(db_session, events, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    called = {"refreshed": False}

    def fake_refresh(s, uid):
        called["refreshed"] = True

    monkeypatch.setattr(tools, "refresh_taste_centroid", fake_refresh)
    tools.record_feedback.invoke({"event_id": "e_music", "sentiment": "dislike"})
    assert called["refreshed"] is False


def test_record_feedback_unknown_event_raises(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")
    with pytest.raises(ToolError, match="event not found"):
        tools.record_feedback.invoke({"event_id": "nope", "sentiment": "like"})


def test_search_events_defaults_to_today_plus_3d(db_session, user, monkeypatch):
    """When both date_from and date_to are omitted, only events in
    today..today+3d (Europe/Berlin) are returned."""
    from datetime import date as _date, timedelta as _td

    today = _date.today()
    in_window = datetime.combine(today + _td(days=1), datetime.min.time(), tzinfo=timezone.utc).replace(hour=20)
    out_window = datetime.combine(today + _td(days=10), datetime.min.time(), tzinfo=timezone.utc).replace(hour=20)

    db_session.add(Event(
        id="e_in", external_id="in1", source="x", title="Soon", description="",
        category="music", source_url="http://x",
        start_datetime=in_window, venue_name="v", is_free=True,
    ))
    db_session.add(Event(
        id="e_out", external_id="out1", source="x", title="Later", description="",
        category="music", source_url="http://x",
        start_datetime=out_window, venue_name="v", is_free=True,
    ))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    results = tools.search_events.invoke({})
    ids = {r["id"] for r in results}
    assert "e_in" in ids
    assert "e_out" not in ids


def test_search_events_explicit_bounds_override_default(db_session, user, monkeypatch):
    from datetime import date as _date, timedelta as _td

    today = _date.today()
    far = datetime.combine(today + _td(days=30), datetime.min.time(), tzinfo=timezone.utc).replace(hour=20)
    db_session.add(Event(
        id="e_far", external_id="far1", source="x", title="Far", description="",
        category="music", source_url="http://x",
        start_datetime=far, venue_name="v", is_free=True,
    ))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    far_iso = (today + _td(days=29)).isoformat()
    far_to_iso = (today + _td(days=31)).isoformat()
    results = tools.search_events.invoke({"date_from": far_iso, "date_to": far_to_iso})
    assert {r["id"] for r in results} == {"e_far"}


def test_search_events_one_bound_does_not_trigger_default(db_session, user, monkeypatch):
    """Caller passing only date_from leaves date_to open — no implicit upper bound."""
    from datetime import date as _date, timedelta as _td

    today = _date.today()
    later = datetime.combine(today + _td(days=10), datetime.min.time(), tzinfo=timezone.utc).replace(hour=20)
    db_session.add(Event(
        id="e_later", external_id="later1", source="x", title="Later", description="",
        category="music", source_url="http://x",
        start_datetime=later, venue_name="v", is_free=True,
    ))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    results = tools.search_events.invoke({"date_from": today.isoformat()})
    assert "e_later" in {r["id"] for r in results}


# ---------------------------------------------------------------------------
# Web search tools
# ---------------------------------------------------------------------------
from unittest.mock import patch


def test_web_search_returns_hits_with_truncated_content():
    fake_hits = [
        {"url": "https://thalia-theater.de/x", "title": "Spielplan",
         "content": "A" * 500},
    ]
    with patch("app.agent.tools.web_research_client.search", return_value=fake_hits):
        from app.agent.tools import web_search
        out = web_search.invoke({"query": "Theater Hamburg"})
    assert len(out) == 1
    assert out[0]["url"] == "https://thalia-theater.de/x"
    # Content is truncated to <= 300 chars.
    assert len(out[0]["content"]) <= 300


def test_web_search_propagates_toolerror_as_string():
    from app.agent.schemas import ToolError
    with patch("app.agent.tools.web_research_client.search", side_effect=ToolError("web search unavailable")):
        from app.agent.tools import web_search
        # ReAct prebuilt agent catches ToolError; here we just verify it is raised.
        import pytest
        with pytest.raises(ToolError):
            web_search.invoke({"query": "x"})


def test_ingest_event_from_url_tool_returns_report(db_session, monkeypatch):
    # Patch SessionLocal so the tool's own session is our in-memory test session.
    monkeypatch.setattr("app.agent.tools.SessionLocal", lambda: db_session)
    fake_report = {"ingested": 2, "updated": 0, "skipped": 0, "event_ids": ["a", "b"]}
    with patch("app.agent.tools.web_research_ingest.ingest_event_from_url", return_value=fake_report):
        from app.agent.tools import ingest_event_from_url
        out = ingest_event_from_url.invoke({"url": "https://thalia-theater.de/x"})
    assert out == fake_report


def test_tools_registered_in_all_tools():
    from app.agent.tools import ALL_TOOLS
    names = [t.name for t in ALL_TOOLS]
    assert "web_search" in names
    assert "ingest_event_from_url" in names
