"""End-to-end digest exercises: events fixture → /digest → cache hit on second call."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import LLMDigestPick, LLMDigestResponse
from app.db.models import DigestCache, Event, User


@pytest.fixture
def populated(db_session):
    db_session.add(User(id="local", interest_tags=["music"], taste_summary="loves jazz", taste_summary_dirty=False))
    for i in range(8):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", description="d", category="music",
            source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i % 3, tzinfo=timezone.utc),
        ))
    db_session.commit()


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.get_agent")
def test_digest_full_cycle_caches(mock_agent, _today, client, populated, db_session):
    response = LLMDigestResponse(picks=[
        LLMDigestPick(event_id=f"e{i}", justification=f"justification number {i}") for i in range(4)
    ])
    fake = MagicMock()
    fake.invoke.return_value = {"structured_response": response}
    mock_agent.return_value = fake

    r1 = client.get("/digest")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["is_cached"] is False
    assert len(body1["picks"]) == 4

    assert db_session.query(DigestCache).filter_by(user_id="local").count() == 1
    fake.invoke.reset_mock()

    r2 = client.get("/digest")
    body2 = r2.json()
    assert body2["is_cached"] is True
    assert [p["event"]["id"] for p in body2["picks"]] == [p["event"]["id"] for p in body1["picks"]]
    fake.invoke.assert_not_called()
