from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
