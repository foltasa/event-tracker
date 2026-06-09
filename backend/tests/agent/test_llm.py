from unittest.mock import patch

from app.agent.llm import build_llm


@patch("app.agent.llm.ChatOpenAI")
def test_build_llm_targets_openrouter(mock_chat):
    build_llm()
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["streaming"] is True


@patch("app.agent.llm.ChatOpenAI")
def test_build_llm_accepts_overrides(mock_chat):
    build_llm(model="anthropic/claude-haiku-4.5", temperature=0.2)
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["model"] == "anthropic/claude-haiku-4.5"
    assert kwargs["temperature"] == 0.2
