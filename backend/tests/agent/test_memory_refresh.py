import uuid
from unittest.mock import patch

import pytest

from app.db.models import Event, Feedback, SavedEvent, User


def _make_event(cat: str, ev_id: str, when="2026-06-01T00:00:00+00:00") -> Event:
    from datetime import datetime
    return Event(
        id=ev_id, external_id=ev_id, source="test",
        title=f"{cat} {ev_id}", description=f"desc {ev_id}",
        start_datetime=datetime.fromisoformat(when),
        category=cat, tags=[], source_url=f"http://e/{ev_id}",
        raw_data={},
    )


def _seed_user(db, user_id="alice", active=None):
    u = User(id=user_id, active_categories=active)
    db.add(u)
    db.flush()
    return u


def test_refresh_taste_centroids_per_category(db_session):
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e1 = _make_event("concerts", "e1")
    e2 = _make_event("party", "e2")
    db_session.add_all([e1, e2])
    db_session.add_all([
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e1", sentiment="like"),
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e2", sentiment="like"),
    ])
    db_session.commit()

    fake_embeddings = {"e1": [1.0, 0.0], "e2": [0.0, 1.0]}
    with patch("app.agent.memory.get_embeddings_for_ids", return_value=fake_embeddings):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert u.taste_centroids["concerts"] == [1.0, 0.0]
    assert u.taste_centroids["party"] == [0.0, 1.0]
    # Fallback global centroid is the mean of category centroids.
    assert u.taste_centroid == [0.5, 0.5]


def test_saved_events_weighted_double_over_likes(db_session):
    """A save-only event pulls the centroid twice as strongly as a like-only event."""
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e_like = _make_event("concerts", "e_like")
    e_save = _make_event("concerts", "e_save")
    db_session.add_all([e_like, e_save])
    db_session.add(Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e_like", sentiment="like"))
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="alice", event_id="e_save"))
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e_like": [1.0, 0.0], "e_save": [0.0, 1.0]},
    ):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    concerts = u.taste_centroids["concerts"]
    # Save weight 2.0, like weight 1.0 → (1*1 + 2*0)/3 = 1/3, (1*0 + 2*1)/3 = 2/3.
    assert concerts[0] == pytest.approx(1 / 3, abs=1e-6)
    assert concerts[1] == pytest.approx(2 / 3, abs=1e-6)


def test_dislikes_do_not_affect_centroid(db_session):
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e1 = _make_event("concerts", "e1")
    e2 = _make_event("concerts", "e2")
    db_session.add_all([e1, e2])
    db_session.add_all([
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e1", sentiment="like"),
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e2", sentiment="dislike"),
    ])
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e1": [1.0, 0.0], "e2": [0.0, 1.0]},
    ):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert u.taste_centroids["concerts"] == [1.0, 0.0]


def test_no_positive_signal_clears_category(db_session):
    from app.agent.memory import refresh_taste_centroids

    u = _seed_user(db_session)
    u.taste_centroids = {"concerts": [0.9, 0.1]}
    db_session.commit()

    with patch("app.agent.memory.get_embeddings_for_ids", return_value={}):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert "concerts" not in u.taste_centroids
    assert u.taste_centroid is None
