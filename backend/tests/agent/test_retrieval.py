from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _mk_event(db, ev_id, cat, title="t", desc="d", tags=None):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title=title, description=desc,
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=tags or [], source_url="http://e",
        raw_data={},
    )
    db.add(e)
    return e


def test_filter_out_disliked_is_passthrough(db_session):
    from app.agent.retrieval import filter_out_disliked
    from app.db.models import User

    _mk_event(db_session, "e_edm", "party", title="Big EDM night", desc="DJ set")
    _mk_event(db_session, "e_ok", "party", title="Techno party", desc="raw sound")
    db_session.commit()

    user = User(
        id="local",
        # Even with dislike facets present, filter must be a no-op.
        taste_facets={"party": {"disliked.genres": {"edm": 1.0}}},
    )
    kept = filter_out_disliked(db_session, user, "party", ["e_edm", "e_ok"])
    assert kept == ["e_edm", "e_ok"]


def test_filter_out_disliked_passthrough_with_empty_facets(db_session):
    from app.agent.retrieval import filter_out_disliked
    from app.db.models import User

    _mk_event(db_session, "e1", "concerts")
    db_session.commit()
    user = User(id="local", taste_facets={})
    assert filter_out_disliked(db_session, user, "concerts", ["e1"]) == ["e1"]


def test_get_category_candidates_returns_empty_when_category_inactive(db_session):
    from app.agent.retrieval import get_category_candidates
    user = User(id="local", active_categories=["concerts"])
    res = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=10)
    assert res == []


def test_get_category_candidates_uses_category_centroid(db_session):
    from app.agent.retrieval import get_category_candidates
    _mk_event(db_session, "e1", "concerts")
    db_session.commit()
    user = User(
        id="local",
        active_categories=["concerts"],
        taste_centroids={"concerts": [1.0, 0.0]},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        q.return_value = [type("H", (), {"event_id": "e1", "similarity_score": 0.9})()]
        res = get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=5)
    assert "e1" in [h.event_id for h in res]
    args, kwargs = q.call_args
    assert args[0] == [1.0, 0.0]
    assert kwargs.get("where", {}).get("category") == "concerts"


def test_get_category_candidates_keyword_first_no_centroid(db_session):
    from app.agent.retrieval import get_category_candidates
    from app.db.models import Event, User
    from datetime import datetime, timezone

    # Two party events at Südpol + 40 generic party events (enough to trigger fill).
    for i in range(40):
        _mk_event(db_session, f"gen_{i}", "party", title=f"Party {i}", desc="")
    e = Event(id="s1", external_id="s1", source="t", title="Loud",
              description="", start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
              category="party", tags=[], source_url="http://e", raw_data={},
              venue_name="Südpol")
    db_session.add(e)
    db_session.commit()

    user = User(
        id="local", active_categories=["party"],
        taste_facets={"party": {"venues": {"südpol": 1.0}}},
        taste_centroids={},
    )
    hits = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=30)
    ids = [h.event_id for h in hits]
    # Südpol match is always in the pool.
    assert "s1" in ids
    # Generic fill kicks in because pool < GENERIC_FLOOR = 30 after keyword pass.
    assert len(ids) >= 30


def test_get_category_candidates_semantic_add_only_if_centroid(db_session):
    from unittest.mock import patch
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    _mk_event(db_session, "kw1", "concerts", title="Nils Frahm live", desc="")
    _mk_event(db_session, "sem1", "concerts")
    db_session.commit()

    user = User(
        id="local", active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"nils frahm": 1.0}}},
        taste_centroids={"concerts": [1.0, 0.0]},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        q.return_value = [type("H", (), {"event_id": "sem1", "similarity_score": 0.9})()]
        hits = get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=30)
    ids = [h.event_id for h in hits]
    assert "kw1" in ids
    assert "sem1" in ids


def test_get_category_candidates_semantic_skipped_without_centroid(db_session):
    from unittest.mock import patch
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    _mk_event(db_session, "kw1", "concerts", title="Nils Frahm live", desc="")
    db_session.commit()
    user = User(
        id="local", active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"nils frahm": 1.0}}},
        taste_centroids={},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=30)
        q.assert_not_called()


def test_get_category_candidates_per_pill_cap_scales_with_pill_count(db_session):
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    # 60 party events, each mentioning both venues.
    for i in range(60):
        _mk_event(db_session, f"p{i}", "party", title=f"Südpol Fundbureau {i}", desc="")
    db_session.commit()

    user = User(
        id="local", active_categories=["party"], taste_centroids={},
        taste_facets={"party": {"venues": {"südpol": 1.0, "fundbureau": 1.0}}},
    )
    hits = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=30)
    # Two pills, target=50 → per_pill_cap = 25. After dedup (both terms match every event)
    # unique events = 25. Then generic fill runs since pool < 30, adding 5 more.
    assert len(hits) >= 30


def test_keyword_hits_matches_venue_name_case_insensitively(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import User

    _mk_event(db_session, "e1", "party", title="Late Night", desc="dj set")
    e = _mk_event(db_session, "e2", "party", title="X", desc="Y")
    e.venue_name = "Südpol Basement"
    _mk_event(db_session, "e3", "party", title="Other", desc="")
    db_session.commit()

    user = User(id="local", taste_facets={"party": {"venues": {"südpol": 1.0}}})
    hits = _keyword_hits_for_category(db_session, user, "party", date_from=None, date_to=None, per_pill_cap=10)
    assert [h.event_id for h in hits] == ["e2"]


def test_keyword_hits_matches_title_and_description_for_artists_and_genres(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import User

    _mk_event(db_session, "e_title", "concerts", title="Nils Frahm live", desc="")
    _mk_event(db_session, "e_desc", "concerts", title="Piano evening", desc="Featuring Nils Frahm")
    _mk_event(db_session, "e_none", "concerts", title="Other", desc="")
    _mk_event(db_session, "e_genre_desc", "concerts", title="Combo", desc="An indie evening")
    db_session.commit()

    user = User(id="local", taste_facets={
        "concerts": {"artists": {"nils frahm": 1.0}, "genres": {"indie": 1.0}},
    })
    hits = _keyword_hits_for_category(db_session, user, "concerts", date_from=None, date_to=None, per_pill_cap=10)
    got = {h.event_id for h in hits}
    assert got == {"e_title", "e_desc", "e_genre_desc"}


def test_keyword_hits_respects_per_pill_cap_and_date_range(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import Event, User
    from datetime import datetime, timezone

    # Two "südpol" party events on different dates.
    e_in = Event(id="in", external_id="in", source="t", title="X", description="d",
                 start_datetime=datetime(2026, 6, 15, tzinfo=timezone.utc),
                 category="party", tags=[], source_url="http://e", raw_data={},
                 venue_name="Südpol")
    e_out = Event(id="out", external_id="out", source="t", title="X", description="d",
                  start_datetime=datetime(2026, 8, 15, tzinfo=timezone.utc),
                  category="party", tags=[], source_url="http://e", raw_data={},
                  venue_name="Südpol")
    db_session.add_all([e_in, e_out])
    db_session.commit()

    user = User(id="local", taste_facets={"party": {"venues": {"südpol": 1.0}}})
    hits = _keyword_hits_for_category(
        db_session, user, "party",
        date_from="2026-06-01", date_to="2026-07-01", per_pill_cap=10,
    )
    assert [h.event_id for h in hits] == ["in"]

    # per_pill_cap = 1 caps the per-pill result to 1 event even when both match.
    hits_capped = _keyword_hits_for_category(
        db_session, user, "party",
        date_from=None, date_to=None, per_pill_cap=1,
    )
    assert len(hits_capped) == 1
