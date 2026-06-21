from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EVENT_CATEGORIES = frozenset({
    "music", "arts", "food", "sports", "tech",
    "outdoor", "film", "theater", "family", "other",
})

EventCategory = Literal[
    "music", "arts", "food", "sports", "tech",
    "outdoor", "film", "theater", "family", "other",
]
Sentiment = Literal["like", "dislike"]
LLMProvider = Literal["openai", "anthropic"]


class _JsonBase(BaseModel):
    """Base model that serializes datetimes as ISO 8601 with `Z` suffix when UTC."""
    model_config = ConfigDict(ser_json_timedelta="iso8601")

    @model_validator(mode="after")
    def _ensure_aware_datetimes(self):
        # SQLite stores timezone-aware datetimes but SQLAlchemy returns them naive.
        # Treat any naive datetime as UTC so JSON output carries a 'Z' suffix and
        # browsers parse the absolute instant correctly instead of as local time.
        for name in type(self).model_fields:
            value = getattr(self, name, None)
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone.utc))
        return self


class EventCard(_JsonBase):
    id: str
    title: str
    summary: str | None
    start_datetime: datetime
    end_datetime: datetime | None
    venue_name: str | None
    venue_address: str | None
    category: EventCategory
    tags: list[str] = Field(default_factory=list)
    price_min: float | None
    price_max: float | None
    is_free: bool
    currency: str = "EUR"
    image_url: str | None
    source_url: str
    source: str
    is_active: bool = True


class EventWithContext(EventCard):
    user_sentiment: Sentiment | None = None
    user_comment: str | None = None
    is_saved: bool = False
    calendar_kind: Literal["saved", "recommendation"] | None = None


class UserSettings(_JsonBase):
    tool_toggles: dict[str, bool] = Field(default_factory=dict)
    llm_provider: LLMProvider = "openai"
    llm_model: str | None = None
    auto_recommendations_enabled: bool = True


class ChatTokenUsage(_JsonBase):
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
