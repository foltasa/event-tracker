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
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    # LangGraph checkpointer
    checkpointer_path: str = "./data/agent.sqlite"

    # Web event search (Tavily)
    tavily_api_key: str | None = None
    web_search_extractor_model: str | None = None
    web_search_max_results: int = 5
    web_search_allowed_domains: str = ""  # CSV; empty = allow all

    # Comma-separated list of origins allowed to call the API (browser CORS).
    # Defaults cover the Next.js dev server on common ports.
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
