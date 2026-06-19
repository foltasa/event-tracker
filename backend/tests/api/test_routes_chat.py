import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage

from app.db.models import ChatMessage, User


def _stub_agent_state(agent) -> None:
    """Give a MagicMock agent a no-op aget_state/aupdate_state so the route's
    heal_orphan_tool_calls call resolves to a no-op without exploding on
    `await MagicMock()`."""
    agent.aget_state = AsyncMock(return_value=SimpleNamespace(values={"messages": []}))
    agent.aupdate_state = AsyncMock(return_value=None)


@pytest.fixture
def user(db_session):
    db_session.add(User(id="local", interest_tags=["music"],
                        taste_summary="loves indie", facts_md="lives in Eimsbüttel"))
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
    _stub_agent_state(fake_agent)

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
    _stub_agent_state(fake_agent)

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
    _stub_agent_state(fake_agent)

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


@patch("app.api.routes_chat.get_agent")
def test_chat_prompt_includes_memory_blocks(mock_get_agent, client, user):
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)
    captured = {}

    async def fake_astream(payload, *args, **kwargs):
        captured["system"] = payload["messages"][0].content
        yield ("messages", (AIMessage(content="ok"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    assert "USER MEMORY" in captured["system"]
    assert "lives in Eimsbüttel" in captured["system"]
    assert "loves indie" in captured["system"]


def test_chat_heals_orphan_tool_calls_before_streaming(client, user, monkeypatch):
    """Each POST /chat must repair any orphan tool_calls left in the
    checkpoint by a prior interrupted turn (asyncio cancellation, watchfiles
    reload, process kill) before invoking the agent. Otherwise the new turn
    dies with INVALID_CHAT_HISTORY the moment the LLM sees the corrupt history.

    We assert the wiring (heal called once with the session_id, before
    astream) — the healer's own behaviour is covered in test_runtime."""
    from app.api import routes_chat

    healer_calls: list[str] = []
    call_order: list[str] = []

    async def fake_heal(agent, thread_id):
        healer_calls.append(thread_id)
        call_order.append("heal")
        return 0

    monkeypatch.setattr(routes_chat, "heal_orphan_tool_calls", fake_heal)

    fake_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        call_order.append("astream")
        yield ("messages", (AIMessage(content="ok"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(routes_chat, "get_agent", _fake_get_agent)

    with client.stream("POST", "/chat", json={"session_id": "sess-x", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    assert healer_calls == ["sess-x"], f"expected one heal call with session_id, got {healer_calls!r}"
    assert call_order[0] == "heal", f"heal must run before astream; got {call_order!r}"


def test_chat_resets_turn_budget(client, user, monkeypatch):
    """Each POST /chat must call set_turn_budget so a prior turn's exhaustion
    does not leak into the next turn.

    We verify via a spy on `set_turn_budget` rather than asserting on the
    ContextVar directly: TestClient runs handlers in a separate task, and a
    Task's ContextVar copy does not propagate back to the test thread.
    """
    from app.api import routes_chat

    calls: list[tuple[int, int]] = []

    def _spy(*, web_search: int, ingest: int) -> None:
        calls.append((web_search, ingest))

    monkeypatch.setattr(routes_chat, "set_turn_budget", _spy)

    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield ("messages", (AIMessage(content="ok"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(routes_chat, "get_agent", _fake_get_agent)

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    assert calls == [(4, 6)], f"expected one reset to defaults, got {calls!r}"
