from unittest.mock import patch

from app.agent import runtime


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
    assert len(kwargs["tools"]) == 11
    tool_names = {t.name for t in kwargs["tools"]}
    assert tool_names == {
        "search_events", "get_recommendations", "record_feedback",
        "save_to_calendar", "get_calendar", "get_user_profile",
        "update_user_profile", "edit_facts", "edit_taste_summary",
        "web_search", "ingest_event_from_url",
    }


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
