from unittest.mock import patch

from app.agent import runtime


@patch("app.agent.runtime.create_react_agent")
@patch("app.agent.runtime.SqliteSaver")
@patch("app.agent.runtime.build_llm")
def test_build_agent_wires_llm_tools_and_checkpointer(mock_llm, mock_saver, mock_create):
    mock_llm.return_value = "FAKE_LLM"
    mock_saver.from_conn_string.return_value.__enter__ = lambda s: "FAKE_CHECKPOINTER"
    mock_saver.from_conn_string.return_value.__exit__ = lambda *a: None

    runtime.build_agent()

    mock_llm.assert_called_once()
    args, kwargs = mock_create.call_args
    assert kwargs["model"] == "FAKE_LLM"
    assert len(kwargs["tools"]) == 9
    tool_names = {t.name for t in kwargs["tools"]}
    assert tool_names == {
        "search_events", "get_recommendations", "record_feedback",
        "save_to_calendar", "get_calendar", "get_user_profile",
        "update_user_profile", "edit_facts", "edit_taste_summary",
    }
