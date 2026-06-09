import json
from unittest.mock import MagicMock, patch

import pytest

from langchain_core.messages import AIMessage

from app.db.models import ChatMessage, User


@pytest.fixture
def user(db_session):
    db_session.add(User(id="local", interest_tags=["music"],
                        taste_summary="loves jazz", taste_summary_dirty=False))
    db_session.commit()


def _sse_events(response_text: str) -> list[dict]:
    events = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@patch("app.api.routes_chat.get_agent")
def test_chat_streams_tokens_and_done(mock_get_agent, client, user, db_session):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        yield ("messages", (AIMessage(content="Hello "), {"langgraph_node": "agent"}))
        yield ("messages", (AIMessage(content="there!"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    assert [e["content"] for e in events if e["type"] == "token"] == ["Hello ", "there!"]


@patch("app.api.routes_chat.get_agent")
def test_chat_mirrors_user_and_assistant_messages_to_db(mock_get_agent, client, user, db_session):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        yield ("messages", (AIMessage(content="reply"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(ChatMessage).filter_by(session_id="s1").order_by(ChatMessage.created_at).all()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "hi"
    assert rows[1].content == "reply"


@patch("app.api.routes_chat.get_agent")
def test_chat_emits_error_event_on_agent_exception(mock_get_agent, client, user):
    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"] or "agent error" in events[-1]["message"]
