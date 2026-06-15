from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.agent import memory
from app.db.models import ChatMessage, Event, Feedback, User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    return u


def test_user_id_contextvar_get_default(monkeypatch):
    monkeypatch.setattr("app.agent.memory.settings.default_user_id", "local")
    memory._current_user_id.set(None)
    assert memory.get_current_user_id() == "local"


def test_user_id_contextvar_set_and_get():
    memory._current_user_id.set("alice")
    try:
        assert memory.get_current_user_id() == "alice"
    finally:
        memory._current_user_id.set(None)


def test_record_message_writes_row(db_session, user):
    memory.record_message(
        session=db_session,
        session_id="s1",
        user_id="local",
        role="user",
        content="hi",
    )
    db_session.commit()
    rows = db_session.query(ChatMessage).filter_by(session_id="s1").all()
    assert len(rows) == 1
    assert rows[0].role == "user"
    assert rows[0].content == "hi"


def test_refresh_taste_centroid_no_likes_sets_null(db_session, user):
    memory.refresh_taste_centroid(db_session, "local")
    db_session.refresh(user)
    assert user.taste_centroid is None


def test_refresh_taste_centroid_averages_liked_embeddings(db_session, user):
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite", title="t",
        category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.add(Feedback(id="f1", user_id="local", event_id="e1", sentiment="like"))
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e1": [0.5] * 1536},
    ):
        memory.refresh_taste_centroid(db_session, "local")

    db_session.refresh(user)
    assert user.taste_centroid is not None
    assert len(user.taste_centroid) == 1536
    assert user.taste_centroid[0] == pytest.approx(0.5)
