from pathlib import Path

from app.config import Settings, settings


def test_agent_settings_have_defaults():
    fields = Settings.model_fields
    assert fields["agent_model"].default == "openai/gpt-4o-mini"
    assert fields["embedding_model"].default == "text-embedding-3-small"
    assert fields["chroma_path"].default == "./data/chroma"
    assert fields["checkpointer_path"].default == "./data/agent.sqlite"


def test_agent_settings_optional_keys():
    assert hasattr(settings, "openrouter_api_key")
    assert not hasattr(settings, "openai_api_key")


def test_settings_env_file_points_to_repo_root():
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).name == ".env"
    # config.py → app → backend → repo  (3 levels up from app/config.py)
    expected_root = Path(__file__).resolve().parents[2]
    assert Path(env_file).parent == expected_root


def test_settings_have_web_search_defaults():
    from app.config import Settings
    s = Settings(_env_file=None)  # ignore .env so we see pure defaults
    assert s.tavily_api_key is None
    assert s.web_search_extractor_model is None
    assert s.web_search_max_results == 5
    assert s.web_search_allowed_domains == ""


def test_settings_pick_up_tavily_from_env(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("WEB_SEARCH_MAX_RESULTS", "3")
    s = Settings(_env_file=None)
    assert s.tavily_api_key == "tvly-test"
    assert s.web_search_max_results == 3
