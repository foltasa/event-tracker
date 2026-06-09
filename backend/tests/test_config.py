from app.config import settings


def test_agent_settings_have_defaults():
    assert settings.agent_model == "openai/gpt-4o-mini"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.chroma_path == "./data/chroma"
    assert settings.checkpointer_path == "./data/agent.sqlite"


def test_agent_settings_optional_keys():
    assert hasattr(settings, "openrouter_api_key")
    assert hasattr(settings, "openai_api_key")
