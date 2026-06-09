from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import LLMDigestPick, LLMDigestResponse
from app.db.models import DigestCache, Event, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=["music"],
                        taste_summary="loves jazz", taste_summary_dirty=False))
    for i in range(5):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", description=f"desc {i}", category="music",
            source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i, tzinfo=timezone.utc),
        ))
    db_session.commit()


def _fake_agent_with_picks(picks):
    agent = MagicMock()
    response = LLMDigestResponse(picks=[LLMDigestPick(event_id=p, justification="because " + p + " is great") for p in picks])
    agent.invoke.return_value = {"structured_response": response}
    return agent


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_generates_on_miss_and_caches(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    r = client.get("/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-06-09"
    assert len(body["picks"]) == 3
    assert body["picks"][0]["event"]["id"] == "e0"
    assert body["is_cached"] is False
    assert db_session.query(DigestCache).filter_by(user_id="local").count() == 1


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_returns_cache_without_invoking_llm(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")  # populate cache
    mock_agent.reset_mock()
    r = client.get("/digest")
    body = r.json()
    assert body["is_cached"] is True
    mock_agent.return_value.invoke.assert_not_called()


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_refresh_overwrites_cache(mock_agent, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")

    mock_agent.return_value = _fake_agent_with_picks(["e3", "e4", "e0"])
    r = client.post("/digest/refresh")
    body = r.json()
    assert {p["event"]["id"] for p in body["picks"]} == {"e3", "e4", "e0"}


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_502_when_agent_returns_too_few_picks(mock_agent, _today, client, setup):
    agent = MagicMock()
    agent.invoke.return_value = {"structured_response": None}
    mock_agent.return_value = agent
    r = client.get("/digest")
    assert r.status_code == 502
