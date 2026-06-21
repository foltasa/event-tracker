import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage, ToolMessage

from app.db.models import ChatMessage, Event, SavedEvent, User


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
        # stream_mode="messages" yields (message_chunk, metadata) 2-tuples
        # directly — no channel-name prefix in langgraph 1.x. The route buffers
        # per message-id and emits when finish_reason is set, so chunks of one
        # logical reply share an id and the final chunk carries the marker.
        yield (AIMessage(content="Hello ", id="m_final"), {"langgraph_node": "agent"})
        yield (
            AIMessage(content="there!", id="m_final", response_metadata={"finish_reason": "stop"}),
            {"langgraph_node": "agent"},
        )

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    # Per-message buffering: the final answer arrives as one concatenated
    # token event, not token-by-token. UX trade-off documented in the route.
    assert [e["content"] for e in events if e["type"] == "token"] == ["Hello there!"]


@patch("app.api.routes_chat.get_agent")
def test_chat_mirrors_user_and_assistant_messages_to_db(mock_get_agent, client, user, db_session):
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="reply"), {"langgraph_node": "agent"})

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
        yield (AIMessage(content="ok"), {"langgraph_node": "agent"})

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
        yield (AIMessage(content="ok"), {"langgraph_node": "agent"})

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
        yield (AIMessage(content="ok"), {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(routes_chat, "get_agent", _fake_get_agent)

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    assert calls == [(4, 6)], f"expected one reset to defaults, got {calls!r}"


@patch("app.api.routes_chat.get_agent")
def test_chat_suppresses_intermediate_reasoning_attached_to_tool_call(
    mock_get_agent, client, user, db_session
):
    """Regression for the 2026-06-19 'gibtLeider' bug.

    A ReAct agent emits AIMessages whose content is internal monologue
    accompanying a tool_call (e.g. 'Hmm, lass mich noch breiter schauen…').
    OpenAI-style streaming sends those content tokens BEFORE the tool_call
    chunks land, which had let them leak through and glue themselves to the
    final answer ('…generell gibtLeider sieht es dünn aus…').

    The route now buffers per message-id and discards the buffer the moment a
    tool_call signal appears on that id, so only the final AIMessage (no
    tool_calls, finish_reason='stop') reaches the client."""
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        # Intermediate message: reasoning text streams first, tool_call chunks
        # arrive in a later chunk, finish_reason='tool_calls' caps the message.
        yield (
            AIMessage(content="Hmm, lass mich noch breiter schauen, was es gibt", id="m1"),
            {"langgraph_node": "agent"},
        )
        yield (
            AIMessage(
                content="",
                id="m1",
                tool_calls=[{"name": "search_events", "args": {}, "id": "call_1"}],
                response_metadata={"finish_reason": "tool_calls"},
            ),
            {"langgraph_node": "agent"},
        )
        yield (
            ToolMessage(content="[]", tool_call_id="call_1", name="search_events"),
            {"langgraph_node": "tools"},
        )
        # Final reply: no tool_calls, finish_reason='stop'.
        yield (
            AIMessage(
                content="Leider sieht es dünn aus.",
                id="m2",
                response_metadata={"finish_reason": "stop"},
            ),
            {"langgraph_node": "agent"},
        )

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "techno?"}) as r:
        body = b"".join(r.iter_bytes()).decode()

    events = _sse_events(body)
    token_contents = [e["content"] for e in events if e["type"] == "token"]

    # Intermediate monologue must not appear anywhere in user-facing tokens.
    assert all("Hmm, lass mich" not in t for t in token_contents), token_contents
    assert all("breiter schauen" not in t for t in token_contents), token_contents
    # The exact glue artefact from the original bug must not occur.
    assert all("gibtLeider" not in t for t in token_contents), token_contents
    # Final answer is delivered intact.
    assert token_contents == ["Leider sieht es dünn aus."]

    # And the persisted assistant row mirrors the final answer only.
    row = db_session.query(ChatMessage).filter_by(session_id="s1", role="assistant").one()
    assert row.content == "Leider sieht es dünn aus."


def test_delete_chat_history_deletes_rows(client, user, db_session, monkeypatch):
    """DELETE /chat/history?session_id=X removes all ChatMessage rows for that
    user + session_id, leaves other sessions alone, and returns 204."""
    from app.api import routes_chat

    async def _noop_clear(thread_id):  # noqa: ARG001
        return None

    monkeypatch.setattr(routes_chat, "clear_session_checkpoint", _noop_clear)

    db_session.add_all([
        ChatMessage(id="m1", session_id="s1", user_id="local", role="user",
                    content="hi", created_at=datetime.now(timezone.utc)),
        ChatMessage(id="m2", session_id="s1", user_id="local", role="assistant",
                    content="hello", created_at=datetime.now(timezone.utc)),
        ChatMessage(id="m3", session_id="s2", user_id="local", role="user",
                    content="other session", created_at=datetime.now(timezone.utc)),
    ])
    db_session.commit()

    res = client.delete("/chat/history?session_id=s1")
    assert res.status_code == 204

    remaining = db_session.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [r.id for r in remaining] == ["m3"]


def test_delete_chat_history_clears_checkpoint(client, user, db_session, monkeypatch):
    """The endpoint must also clear the LangGraph checkpoint for that thread,
    or the next turn would still see the deleted conversation in agent state."""
    from app.api import routes_chat

    called_with: list[str] = []

    async def _spy_clear(thread_id: str) -> None:
        called_with.append(thread_id)

    monkeypatch.setattr(routes_chat, "clear_session_checkpoint", _spy_clear)

    res = client.delete("/chat/history?session_id=demo-1")
    assert res.status_code == 204
    assert called_with == ["demo-1"]


def _seed_events(db_session, ids: list[str]) -> None:
    for i, eid in enumerate(ids):
        db_session.add(Event(
            id=eid, external_id=f"x{i}", source="eventbrite",
            title=f"t{i}", category="music", source_url=f"http://{eid}",
            start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        ))
    db_session.commit()


@patch("app.api.routes_chat.get_agent")
def test_chat_persists_recommendations_from_event_refs(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1", "e2"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (
            AIMessage(
                content="Try Jazz [event:e1] or Theatre [event:e2].",
                id="m1",
                response_metadata={"finish_reason": "stop"},
            ),
            {"langgraph_node": "agent"},
        )

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "what?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).filter_by(user_id="local").all()
    assert {(r.event_id, r.kind) for r in rows} == {
        ("e1", "recommendation"), ("e2", "recommendation"),
    }


@patch("app.api.routes_chat.get_agent")
def test_chat_skips_recommendations_when_setting_disabled(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    u = db_session.query(User).filter_by(id="local").one()
    u.settings = {"auto_recommendations_enabled": False}
    db_session.commit()

    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="Try [event:e1].", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    assert db_session.query(SavedEvent).count() == 0


@patch("app.api.routes_chat.get_agent")
def test_chat_skips_unknown_event_ids(mock_get_agent, client, user, db_session):
    _seed_events(db_session, ["e1"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="See [event:e1] and [event:ghost].", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).all()
    assert [r.event_id for r in rows] == ["e1"]


@patch("app.api.routes_chat.get_agent")
def test_chat_does_not_downgrade_already_saved_event(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    db_session.add(SavedEvent(id="pre", user_id="local", event_id="e1", kind="saved"))
    db_session.commit()

    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="[event:e1]", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).filter_by(event_id="e1").all()
    assert len(rows) == 1
    assert rows[0].kind == "saved"


@patch("app.api.routes_chat.get_agent")
def test_chat_recommendation_insert_is_idempotent_on_re_mention(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="[event:e1] [event:e1]", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1
