import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.schemas.calendar import CalendarResponse
from app.schemas.chat import ChatChunk
from app.schemas.common import EventWithContext, UserSettings
from app.schemas.digest import DigestResponse
from app.schemas.events import EventsFeedResponse
from app.schemas.profile import UserProfileResponse
from app.schemas.usage import UsageRollupResponse

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "fixtures"

FIXTURE_TO_SCHEMA = [
    ("digest.json",        DigestResponse),
    ("events.json",        EventsFeedResponse),
    ("event-detail.json",  EventWithContext),
    ("calendar.json",      CalendarResponse),
    ("profile.json",       UserProfileResponse),
    ("settings.json",      UserSettings),
    ("usage.json",         UsageRollupResponse),
]


@pytest.mark.parametrize("filename,schema", FIXTURE_TO_SCHEMA)
def test_fixture_validates_against_schema(filename, schema):
    path = FIXTURES_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema.model_validate(payload)


def test_chat_stream_fixture_is_valid_chunks():
    path = FIXTURES_DIR / "chat-stream.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    adapter = TypeAdapter(list[ChatChunk])
    chunks = adapter.validate_python(payload)
    # Stream MUST end with exactly one done or error.
    assert chunks[-1].type in {"done", "error"}
    assert sum(1 for c in chunks if c.type in {"done", "error"}) == 1
