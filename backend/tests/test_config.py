from app.config import settings


def test_agent_settings_have_defaults():
    assert settings.agent_model == "openai/gpt-4o-mini"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.chroma_path == "./data/chroma"
    assert settings.checkpointer_path == "./data/agent.sqlite"


def test_agent_settings_optional_keys():
    assert hasattr(settings, "openrouter_api_key")
    assert hasattr(settings, "openai_api_key")


from pathlib import Path
from app.config import Settings


def test_settings_env_file_points_to_repo_root():
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).name == ".env"
    # config.py → app → backend → repo  (3 levels up from app/config.py)
    expected_root = Path(__file__).resolve().parents[2]
    assert Path(env_file).parent == expected_root
