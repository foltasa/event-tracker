from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import Event, Feedback, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=["music"]))
    db_session.add(Event(
        id="e1", external_id="x", source="eventbrite",
        title="Jazz", category="music", source_url="http://x",
        start_datetime=datetime(2026, 6, 10, tzinfo=timezone.utc),
    ))
    db_session.commit()


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_like_inserts_and_refreshes(mock_refresh, client, setup, db_session):
    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "like", "comment": "loved it"})
    assert r.status_code == 200
    row = db_session.query(Feedback).filter_by(event_id="e1").one()
    assert row.sentiment == "like"
    assert row.comment == "loved it"
    user = db_session.query(User).filter_by(id="local").one()
    assert user.taste_summary_dirty is True
    mock_refresh.assert_called_once()


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_dislike_skips_refresh(mock_refresh, client, setup):
    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "dislike"})
    assert r.status_code == 200
    mock_refresh.assert_not_called()


def test_post_feedback_unknown_event_404(client, setup):
    r = client.post("/feedback", json={"event_id": "nope", "sentiment": "like"})
    assert r.status_code == 404


@patch("app.api.routes_feedback.refresh_taste_centroid")
def test_post_feedback_upserts_on_repeat(mock_refresh, client, setup, db_session):
    client.post("/feedback", json={"event_id": "e1", "sentiment": "like"})
    client.post("/feedback", json={"event_id": "e1", "sentiment": "dislike", "comment": "changed mind"})
    rows = db_session.query(Feedback).filter_by(event_id="e1").all()
    assert len(rows) == 1
    assert rows[0].sentiment == "dislike"
    assert rows[0].comment == "changed mind"
