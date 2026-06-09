import pytest
from pydantic import ValidationError

from app.agent.schemas import EventSummary, LLMDigestPick, LLMDigestResponse, ToolError


def test_llm_digest_response_enforces_3_to_5_picks():
    too_few = [LLMDigestPick(event_id=str(i), justification="j") for i in range(2)]
    with pytest.raises(ValidationError):
        LLMDigestResponse(picks=too_few)

    too_many = [LLMDigestPick(event_id=str(i), justification="j") for i in range(6)]
    with pytest.raises(ValidationError):
        LLMDigestResponse(picks=too_many)

    just_right = [LLMDigestPick(event_id=str(i), justification="j") for i in range(4)]
    LLMDigestResponse(picks=just_right)


def test_event_summary_fields():
    s = EventSummary(
        id="e1", title="t", category="music",
        start_datetime="2026-06-10T20:00:00Z", venue_name="Mojo",
        is_free=False, source_url="http://x",
    )
    assert s.id == "e1"


def test_tool_error_is_exception():
    err = ToolError("nope")
    assert isinstance(err, Exception)
    assert str(err) == "nope"
