from pydantic import Field

from app.schemas.common import LLMProvider, UserSettings, _JsonBase


class UserProfileResponse(_JsonBase):
    city: str
    interest_tags: list[str] = Field(default_factory=list)
    about_me: str | None
    taste_summary: str | None
    settings: UserSettings


class UserProfileUpdate(_JsonBase):
    interest_tags: list[str] | None = None
    about_me: str | None = None


class OnboardingRequest(_JsonBase):
    interest_tags: list[str] = Field(default_factory=list)
    about_me: str | None = None


class SettingsUpdate(_JsonBase):
    tool_toggles: dict[str, bool] | None = None
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None
    auto_recommendations_enabled: bool | None = None
