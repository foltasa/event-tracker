"""Internal models used by the agent layer (tools, structured outputs).
NOT to be confused with `app/schemas/`, which are API contract models."""
from datetime import datetime

from pydantic import BaseModel, Field


class ToolError(Exception):
    """Raised by tool functions on user-facing failures.

    Converted into a ToolMessage by the ToolNode's `handle_tool_errors`
    callback in `runtime.py`. Without that callback, langgraph's default
    handler re-raises everything except ToolInvocationError, which would
    crash the graph mid-step and leave the checkpoint with an orphaned
    AIMessage(tool_calls=...) — every subsequent turn would then fail with
    INVALID_CHAT_HISTORY."""


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
    justification: str = Field(min_length=10)


class LLMDigestResponse(BaseModel):
    picks: list[LLMDigestPick] = Field(min_length=3, max_length=5)
