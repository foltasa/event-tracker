from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event, feedback as _feedback, user as _user  # noqa: F401
from app.db.models.event import Event
from app.db.models.feedback import Feedback
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.add(Event(
        id="evt_1", external_id="x", source="eventbrite", title="t",
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        category="music", tags=[], is_free=False, source_url="https://x", raw_data={},
    ))
    db_session.commit()


def test_feedback_creation(db_session):
    _seed(db_session)
    fb = Feedback(id="fb_1", user_id="local", event_id="evt_1", sentiment="like", comment="great")
    db_session.add(fb)
    db_session.commit()
    db_session.refresh(fb)
    assert fb.sentiment == "like"
    assert fb.comment == "great"
    assert isinstance(fb.created_at, datetime)
    assert isinstance(fb.updated_at, datetime)


def test_feedback_unique_per_user_event(db_session):
    _seed(db_session)
    db_session.add(Feedback(id="fb_1", user_id="local", event_id="evt_1", sentiment="like"))
    db_session.commit()
    db_session.add(Feedback(id="fb_2", user_id="local", event_id="evt_1", sentiment="dislike"))
    with pytest.raises(IntegrityError):
        db_session.commit()
