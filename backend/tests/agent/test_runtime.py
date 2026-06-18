from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
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
