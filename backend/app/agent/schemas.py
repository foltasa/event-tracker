"""Internal models used by the agent layer (tools, structured outputs).
NOT to be confused with `app/schemas/`, which are API contract models."""
from datetime import datetime

from pydantic import BaseModel, Field


class ToolError(Exception):
    """Raised by tool functions on user-facing failures.
    The prebuilt LangGraph agent catches and forwards the message to the LLM."""


class EventSummary(BaseModel):
    """Compact event shape returned by read tools."""
    id: str
    title: str
    category: str
    start_datetime: datetime
    venue_name: str | None = None
    is_free: bool = False
    price_min: float | None = None
    source_url: str
    similarity_score: float | None = None


class LLMDigestPick(BaseModel):
    event_id: str
    justification: str  # plain str — tests pass "j" (length 1); min_length would break test setup


class LLMDigestResponse(BaseModel):
    picks: list[LLMDigestPick] = Field(min_length=3, max_length=5)
