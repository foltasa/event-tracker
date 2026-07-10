from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _mk_event(db, ev_id, cat):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title="t", description="d",
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=[], source_url="http://e", raw_data={},
    )
    db.add(e)
    return e


def test_get_recommendations_returns_no_active_categories_error(db_session, monkeypatch):
    from app.agent import memory, tools
    from app.agent.tools import get_recommendations

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    db_session.add(User(id="local", active_categories=[]))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_recommendations.invoke({})
    assert result == {"error": "no_active_categories"}


def test_get_recommendations_honors_explicit_category_overriding_inactive(db_session, monkeypatch):
    from app.agent import memory, tools
    from app.agent.tools import get_recommendations

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    _mk_event(db_session, "e1", "party")
    db_session.add(User(
        id="local",
        active_categories=[],
        taste_centroids={"party": [1.0, 0.0]},
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    with patch("app.agent.tools.retrieval.get_category_candidates") as q:
        q.return_value = [type("H", (), {"event_id": "e1", "similarity_score": 0.9})()]
        result = get_recommendations.invoke({"category": "party"})
    assert isinstance(result, list) and result[0]["id"] == "e1"


def test_get_recommendations_iterates_over_active_categories(db_session, monkeypatch):
    from app.agent import memory, tools
    from app.agent.tools import get_recommendations

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    _mk_event(db_session, "e1", "concerts")
    _mk_event(db_session, "e2", "party")
    db_session.add(User(
        id="local",
        active_categories=["concerts", "party"],
        taste_centroids={"concerts": [1.0, 0.0], "party": [0.0, 1.0]},
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    def fake_candidates(session, user, category, **kwargs):
        return [
            type("H", (), {"event_id": {"concerts": "e1", "party": "e2"}[category], "similarity_score": 0.9})()
        ]

    with patch("app.agent.tools.retrieval.get_category_candidates", side_effect=fake_candidates):
        result = get_recommendations.invoke({})
    ids = {r["id"] for r in result}
    assert ids == {"e1", "e2"}
