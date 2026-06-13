from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # config.py -> app -> backend -> repo


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    # Agent / LLM
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None  # retained until Task 3 removes it
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7
    summary_model: str = "openai/gpt-4o-mini"

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    # LangGraph checkpointer
    checkpointer_path: str = "./data/agent.sqlite"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
