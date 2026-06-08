from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.common import ChatTokenUsage, EventCard, EventWithContext, UserSettings


def _card_kwargs(**overrides):
    base = dict(
        id="evt_1", title="Jazz", summary="trio",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc),
        end_datetime=None, venue_name="Mojo", venue_address="Reeperbahn 1",
        category="music", tags=["jazz"],
        price_min=18.0, price_max=24.0, is_free=False, currency="EUR",
        image_url="https://x/img.jpg", source_url="https://x/e/1", source="eventbrite",
        is_active=True,
    )
    base.update(overrides)
    return base


def test_event_card_serializes_with_iso_datetimes():
    card = EventCard(**_card_kwargs())
    dumped = card.model_dump(mode="json")
    # Accept either "Z" suffix or "+00:00" offset for UTC.
    assert dumped["start_datetime"].startswith("2026-06-14T20:00:00")
    assert dumped["category"] == "music"


def test_event_card_rejects_invalid_category():
    with pytest.raises(ValidationError):
        EventCard(**_card_kwargs(category="nope"))


def test_event_with_context_extends_card():
    ctx = EventWithContext(**_card_kwargs(), user_sentiment="like", user_comment="great", is_saved=True)
    assert ctx.user_sentiment == "like"
    assert ctx.is_saved is True


def test_event_with_context_allows_null_sentiment():
    ctx = EventWithContext(**_card_kwargs(), user_sentiment=None, user_comment=None, is_saved=False)
    assert ctx.user_sentiment is None


def test_user_settings_shape():
    s = UserSettings(
        tool_toggles={"search_events": True},
        llm_provider="openai",
        llm_model="gpt-4o-mini",
    )
    assert s.llm_provider == "openai"


def test_user_settings_rejects_invalid_provider():
    with pytest.raises(ValidationError):
        UserSettings(tool_toggles={}, llm_provider="meta", llm_model=None)


def test_chat_token_usage():
    u = ChatTokenUsage(input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)
    assert u.estimated_cost_usd == 0.001
