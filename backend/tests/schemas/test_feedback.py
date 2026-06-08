from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.feedback import FeedbackCreate, FeedbackResponse


def test_feedback_create():
    fc = FeedbackCreate(event_id="e1", sentiment="like", comment="loved it")
    assert fc.sentiment == "like"


def test_feedback_create_rejects_invalid_sentiment():
    with pytest.raises(ValidationError):
        FeedbackCreate(event_id="e1", sentiment="meh", comment=None)


def test_feedback_response():
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    fr = FeedbackResponse(id="fb_1", event_id="e1", sentiment="like", comment=None, created_at=now, updated_at=now)
    dumped = fr.model_dump(mode="json")
    assert dumped["sentiment"] == "like"
    assert dumped["comment"] is None
