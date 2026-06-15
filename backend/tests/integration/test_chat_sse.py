"""End-to-end /chat exercise: fake LLM yields tokens and a tool call,
SSE stream contains expected events, chat_messages rows are written."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import ChatMessage, User


@pytest.fixture
def user(db_session):
    db_session.add(User(id="local", interest_tags=["music"], taste_summary="loves jazz", facts_md=""))
    db_session.commit()


def _events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


@patch("app.api.routes_chat.get_agent")
def test_chat_yields_token_tool_done(mock_get_agent, client, user, db_session):
    from langchain_core.messages import AIMessage, ToolMessage

    async def stream(*args, **kwargs):
        yield ("messages", (AIMessage(content="Sure, let me check. ", tool_calls=[]), {}))
        yield ("messages", (AIMessage(content="", tool_calls=[{"name": "search_events", "args": {}, "id": "t1"}]), {}))
        yield ("messages", (ToolMessage(content="[]", tool_call_id="t1", name="search_events"), {}))
        yield ("messages", (AIMessage(content="Nothing matched.", tool_calls=[]), {}))

    fake = MagicMock()
    fake.astream = stream
    mock_get_agent.return_value = fake

    with client.stream("POST", "/chat", json={"session_id": "sess1", "message": "anything good?"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _events(body)
    types = [e["type"] for e in events]
    assert "token" in types
    assert "tool_start" in types
    assert "tool_end" in types
    assert types[-1] == "done"
    assert next(e for e in events if e["type"] == "tool_start")["tool_name"] == "search_events"

    rows = db_session.query(ChatMessage).filter_by(session_id="sess1").all()
    assert {r.role for r in rows} == {"user", "assistant"}
