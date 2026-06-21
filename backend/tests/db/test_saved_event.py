from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event, saved_event as _saved, user as _user  # noqa: F401
from app.db.models.event import Event
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.add(Event(
        id="evt_1", external_id="x", source="eventbrite", title="t",
        start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        category="music", tags=[], is_free=False, source_url="https://x", raw_data={},
    ))
    db_session.commit()


def test_saved_event_creation(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert isinstance(s.saved_at, datetime)


def test_saved_event_unique_per_user_event(db_session):
    _seed(db_session)
    db_session.add(SavedEvent(id="sav_1", user_id="local", event_id="evt_1"))
    db_session.commit()
    db_session.add(SavedEvent(id="sav_2", user_id="local", event_id="evt_1"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_saved_event_kind_defaults_to_saved(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert s.kind == "saved"


def test_saved_event_kind_can_be_recommendation(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1", kind="recommendation")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert s.kind == "recommendation"
