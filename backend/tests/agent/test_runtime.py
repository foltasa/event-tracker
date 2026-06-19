import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from app.agent import runtime
from app.agent.schemas import ToolError


@patch("app.agent.runtime.create_react_agent")
@patch("app.agent.runtime.SqliteSaver")
@patch("app.agent.runtime.sqlite3.connect")
@patch("app.agent.runtime.build_llm")
def test_build_agent_wires_llm_tools_and_checkpointer(
    mock_llm, mock_connect, mock_saver, mock_create
):
    runtime._checkpointer_conn = None
    mock_llm.return_value = "FAKE_LLM"
    mock_connect.return_value = "FAKE_CONN"
    mock_saver.return_value = "FAKE_CHECKPOINTER"

    runtime.build_agent()

    mock_llm.assert_called_once()
    mock_saver.assert_called_once_with("FAKE_CONN")
    args, kwargs = mock_create.call_args
    assert kwargs["model"] == "FAKE_LLM"
    assert kwargs["checkpointer"] == "FAKE_CHECKPOINTER"
    # Tools are now wrapped in a ToolNode so we can attach handle_tool_errors.
    assert isinstance(kwargs["tools"], ToolNode)
    tool_names = set(kwargs["tools"].tools_by_name.keys())
    assert tool_names == {
        "search_events", "get_recommendations", "record_feedback",
        "save_to_calendar", "get_calendar", "get_user_profile",
        "update_user_profile", "edit_facts", "edit_taste_summary",
        "web_search", "ingest_event_from_url",
    }


def test_handle_tool_errors_converts_any_exception_to_string():
    """Direct unit test of the handler. Regression: langgraph's default handler
    re-raises every exception except ToolInvocationError. Ours must catch
    everything so the ToolNode emits a ToolMessage instead of crashing the
    graph mid-step and leaving an orphaned AIMessage(tool_calls) in the
    checkpoint (which then dies with INVALID_CHAT_HISTORY on the next turn)."""
    out_tool_error = runtime._handle_tool_errors(ToolError("boom"))
    assert "boom" in out_tool_error
    out_generic = runtime._handle_tool_errors(RuntimeError("oops"))
    assert "oops" in out_generic


@patch("app.agent.runtime.create_react_agent")
@patch("app.agent.runtime.SqliteSaver")
@patch("app.agent.runtime.sqlite3.connect")
@patch("app.agent.runtime.build_llm")
def test_build_agent_wires_handle_tool_errors_into_toolnode(
    mock_llm, mock_connect, mock_saver, mock_create
):
    """Verify the wiring: build_agent must hand a ToolNode to create_react_agent,
    and that ToolNode's _handle_tool_errors must be our handler (not the
    langgraph default that re-raises ToolError)."""
    runtime._checkpointer_conn = None

    runtime.build_agent()

    _, kwargs = mock_create.call_args
    node = kwargs["tools"]
    assert isinstance(node, ToolNode)
    assert node._handle_tool_errors is runtime._handle_tool_errors


@patch("app.agent.runtime.create_react_agent")
@patch("app.agent.runtime.sqlite3.connect")
@patch("app.agent.runtime.build_llm")
def test_checkpointer_connection_reused_across_builds(mock_llm, mock_connect, _mock_create):
    """Regression: closing the saver between builds broke later agent.invoke calls."""
    runtime._checkpointer_conn = None
    mock_connect.return_value = "FAKE_CONN"

    runtime.build_agent()
    runtime.build_agent()

    assert mock_connect.call_count == 1


# -----------------------------------------------------------------------------
# heal_orphan_tool_calls — repair INVALID_CHAT_HISTORY left by an interrupted
# prior turn. SqliteSaver checkpoints between the LLM step and the ToolNode
# step. If the ToolNode is interrupted from outside the tool body (asyncio
# cancellation on client disconnect, watchfiles reload, process kill), the
# AIMessage(tool_calls=[...]) persists with no matching ToolMessages and every
# subsequent turn dies with INVALID_CHAT_HISTORY. The healer fills the gap.
# -----------------------------------------------------------------------------


def _fake_agent(messages: list) -> SimpleNamespace:
    """Build a minimal stand-in for a compiled LangGraph agent — only the
    methods heal_orphan_tool_calls touches (aget_state, aupdate_state) are
    present, both as AsyncMocks. aget_state returns a snapshot whose .values
    contains the provided messages, mirroring the real shape."""
    state = SimpleNamespace(values={"messages": messages})
    agent = SimpleNamespace()
    agent.aget_state = AsyncMock(return_value=state)
    agent.aupdate_state = AsyncMock(return_value=None)
    return agent


def test_heal_orphan_tool_calls_injects_synthetic_messages_for_each_orphan():
    """Prior turn was interrupted after the AIMessage with two tool_calls was
    checkpointed but before the ToolNode emitted matching ToolMessages. The
    healer must inject one ToolMessage per orphan tool_call, carrying the
    original call id and name."""
    orphan_ai = AIMessage(
        content="Let me dig into these promising leads.",
        tool_calls=[
            {"name": "ingest_event_from_url", "args": {"url": "https://a.example"}, "id": "call_a", "type": "tool_call"},
            {"name": "ingest_event_from_url", "args": {"url": "https://b.example"}, "id": "call_b", "type": "tool_call"},
        ],
    )
    agent = _fake_agent([HumanMessage(content="hi"), orphan_ai])

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-x"))

    assert healed == 2
    agent.aupdate_state.assert_called_once()
    call_args, _ = agent.aupdate_state.call_args
    config_arg, update_arg = call_args
    assert config_arg == {"configurable": {"thread_id": "thread-x"}}
    injected = update_arg["messages"]
    assert [type(m).__name__ for m in injected] == ["ToolMessage", "ToolMessage"]
    assert [m.tool_call_id for m in injected] == ["call_a", "call_b"]
    assert all(m.name == "ingest_event_from_url" for m in injected)
    # Content must be a plain string so the LLM treats it as a benign no-op
    # result rather than something to retry or echo.
    assert all(isinstance(m.content, str) and m.content for m in injected)


def test_heal_orphan_tool_calls_is_noop_when_history_is_valid():
    """Properly-paired history must not be touched (no aupdate_state call)."""
    messages = [
        HumanMessage(content="find me jazz"),
        AIMessage(content="", tool_calls=[{"name": "search_events", "args": {}, "id": "call_1", "type": "tool_call"}]),
        ToolMessage(content="[]", tool_call_id="call_1", name="search_events"),
        AIMessage(content="Nothing matched."),
    ]
    agent = _fake_agent(messages)

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-x"))

    assert healed == 0
    agent.aupdate_state.assert_not_called()


def test_heal_orphan_tool_calls_only_patches_the_unanswered_calls():
    """If one of two parallel tool_calls already has a ToolMessage and the
    other does not (e.g. cancellation hit between the two writes), only the
    missing one gets a synthetic message."""
    orphan_ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_events", "args": {}, "id": "call_done", "type": "tool_call"},
            {"name": "ingest_event_from_url", "args": {"url": "https://x"}, "id": "call_orphan", "type": "tool_call"},
        ],
    )
    messages = [
        HumanMessage(content="anything?"),
        orphan_ai,
        ToolMessage(content="[]", tool_call_id="call_done", name="search_events"),
    ]
    agent = _fake_agent(messages)

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-x"))

    assert healed == 1
    _, update_arg = agent.aupdate_state.call_args[0]
    injected = update_arg["messages"]
    assert len(injected) == 1
    assert injected[0].tool_call_id == "call_orphan"
    assert injected[0].name == "ingest_event_from_url"


def test_heal_orphan_tool_calls_handles_empty_thread():
    """A thread with no messages yet (first-ever turn) must be a no-op."""
    agent = _fake_agent([])

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-new"))

    assert healed == 0
    agent.aupdate_state.assert_not_called()


def test_heal_orphan_tool_calls_ignores_older_orphans_beyond_latest_ai_message():
    """Only the *latest* AIMessage matters for INVALID_CHAT_HISTORY validation.
    Older AIMessages with tool_calls are, by construction, inside a valid
    prefix (otherwise earlier turns would already have failed); the healer
    must not double-patch them."""
    older_ai = AIMessage(
        content="",
        tool_calls=[{"name": "search_events", "args": {}, "id": "old_call", "type": "tool_call"}],
    )
    # Note: deliberately no ToolMessage for old_call to simulate a hypothetical
    # legacy state. The healer should still only look at the latest AIMessage.
    latest_ai = AIMessage(
        content="",
        tool_calls=[{"name": "ingest_event_from_url", "args": {}, "id": "new_call", "type": "tool_call"}],
    )
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="q1"),
        older_ai,
        HumanMessage(content="q2"),
        latest_ai,
    ]
    agent = _fake_agent(messages)

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-x"))

    assert healed == 1
    _, update_arg = agent.aupdate_state.call_args[0]
    injected = update_arg["messages"]
    assert len(injected) == 1
    assert injected[0].tool_call_id == "new_call"


def test_heal_orphan_tool_calls_is_noop_when_latest_ai_message_has_no_tool_calls():
    """A normal terminal AIMessage (final assistant reply, no tool_calls) is
    not an orphan."""
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="Hello!"),
    ]
    agent = _fake_agent(messages)

    healed = asyncio.run(runtime.heal_orphan_tool_calls(agent, "thread-x"))

    assert healed == 0
    agent.aupdate_state.assert_not_called()
