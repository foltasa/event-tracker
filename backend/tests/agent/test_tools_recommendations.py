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


def test_get_recommendations_ranks_keyword_hits_before_fill(db_session, monkeypatch):
    """Regression: with Chroma empty (no centroid), keyword hits and generic
    fill both carried similarity_score=None. The tool then sorted by that
    None → 0.0 and sliced to n, so keyword-hit events could be shoved out of
    the top-n by lexicographically-earlier fill rows. The tool must return
    keyword hits before any generic fill regardless of DB insertion order."""
    from app.agent import memory, tools
    from app.agent.tools import get_recommendations
    from app.db.models import Event, User

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    # 15 generic party events inserted first (so their rowids come before the
    # keyword hits). Non-matching venue.
    for i in range(15):
        db_session.add(Event(
            id=f"0000000{i:02d}", external_id=f"g{i}", source="t",
            title=f"Generic {i}", description="",
            start_datetime=datetime(2026, 7, 15, tzinfo=timezone.utc),
            category="party", tags=[], source_url="http://e", raw_data={},
            venue_name="Some Club",
        ))
    # 3 keyword-hit events at Fundbureau inserted afterwards.
    kw_ids = [f"{p}{'0' * 35}" for p in ("f", "g", "h")]
    for i, eid in enumerate(kw_ids):
        db_session.add(Event(
            id=eid, external_id=f"kw{i}", source="t",
            title=f"Fundbureau night {i}", description="",
            start_datetime=datetime(2026, 7, 16, tzinfo=timezone.utc),
            category="party", tags=[], source_url="http://e", raw_data={},
            venue_name="Fundbureau",
        ))
    db_session.add(User(
        id="local", active_categories=["party"],
        taste_facets={"party": {"venues": {"fundbureau": 1.0}}},
        taste_centroids={},  # no centroid → semantic path skipped
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_recommendations.invoke({"n": 5})
    ids = [r["id"] for r in result]

    keyword_positions = [i for i, eid in enumerate(ids) if eid in kw_ids]
    generic_positions = [i for i, eid in enumerate(ids) if eid.startswith("0")]
    assert len(keyword_positions) == 3, f"expected all 3 keyword hits in top 5, got {ids}"
    if generic_positions:
        assert max(keyword_positions) < min(generic_positions), \
            f"keyword hits must precede generic fill; got {ids}"


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
