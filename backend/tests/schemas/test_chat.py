from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.chat import (
    ChatChunk, ChatChunkDone, ChatChunkError, ChatChunkToken, ChatChunkToolEnd, ChatChunkToolStart,
    ChatMessageResponse, ChatRequest,
)
from app.schemas.common import ChatTokenUsage


def test_chat_request():
    r = ChatRequest(message="hi", session_id="sess_1")
    assert r.session_id == "sess_1"


def test_chat_chunk_token():
    c = ChatChunkToken(type="token", content="hi")
    assert c.content == "hi"


def test_chat_chunk_tool_start():
    c = ChatChunkToolStart(type="tool_start", tool_name="search_events")
    assert c.tool_name == "search_events"


def test_chat_chunk_tool_end_status():
    c = ChatChunkToolEnd(type="tool_end", tool_name="search_events", status="ok")
    assert c.status == "ok"


def test_chat_chunk_tool_end_rejects_invalid_status():
    with pytest.raises(ValidationError):
        ChatChunkToolEnd(type="tool_end", tool_name="search_events", status="bad")


def test_chat_chunk_done():
    c = ChatChunkDone(type="done", token_usage=ChatTokenUsage(input_tokens=1, output_tokens=2, estimated_cost_usd=0.001))
    assert c.token_usage.input_tokens == 1


def test_chat_chunk_error():
    c = ChatChunkError(type="error", message="rate limited")
    assert c.message == "rate limited"


def test_chat_chunk_union_discriminator():
    adapter = TypeAdapter(ChatChunk)
    parsed = adapter.validate_python({"type": "token", "content": "hi"})
    assert isinstance(parsed, ChatChunkToken)
    parsed2 = adapter.validate_python({"type": "done", "token_usage": {"input_tokens": 1, "output_tokens": 2, "estimated_cost_usd": 0.001}})
    assert isinstance(parsed2, ChatChunkDone)


def test_chat_message_response():
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    m = ChatMessageResponse(
        id="msg_1", session_id="sess_1", role="assistant", content="hello",
        tool_name=None, token_usage=None, created_at=now,
    )
    assert m.role == "assistant"
