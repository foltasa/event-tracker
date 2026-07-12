from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # config.py -> app -> backend -> repo


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    # When True (default), list endpoints, agent tools, and the embedding
    # feed skip events whose description is null or empty. Flip via
    # HIDE_EVENTS_WITHOUT_DESCRIPTION=false in .env to include them
    # (useful during backfill validation).
    hide_events_without_description: bool = True

    # Agent / LLM
    openrouter_api_key: str | None = None
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7

    # Event categorization LLM (used by ingestion pipeline)
    categorization_model: str = "google/gemini-2.5-flash"
    categorization_timeout_seconds: float = 10.0

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    # LangGraph checkpointer
    checkpointer_path: str = "./data/agent.sqlite"

    # Web event search (Tavily)
    # Master switch — when False the agent does not get the web_search /
    # ingest_event_from_url tools and the conversational prompt omits the
    # web-search strategy block. Defaults to False until the feature is
    # reliable; flip via WEB_SEARCH_ENABLED=true in .env to reactivate.
    web_search_enabled: bool = False
    tavily_api_key: str | None = None
    web_search_extractor_model: str | None = None
    web_search_max_results: int = 5
    web_search_allowed_domains: str = ""  # CSV; empty = allow all

    # Comment extractor — when False the feedback POST and About-Me PUT do not
    # schedule the LLM-driven extractor background task. Facets remain
    # user-editable via the About Me form; behaviour signals still feed
    # taste_centroids via refresh_taste_centroids.
    comment_extractor_enabled: bool = False

    # Comma-separated list of origins allowed to call the API (browser CORS).
    # Defaults cover the Next.js dev server on common ports.
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
