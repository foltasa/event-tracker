from unittest.mock import MagicMock

from app.agent.comment_extractor import ExtractorInput, extract_and_apply


def test_extractor_applies_facet_updates_to_user(db_session):
    from app.db.models import User
    u = User(id="local", taste_facets={"concerts": {"artists": {"Existing": 0.5}}})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.return_value.facet_updates = [
        _fu("concerts", "artists", "Tocotronic", 0.3),
        _fu("concerts", "disliked.genres", "edm", 1.0),
    ]

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "Konzert", "venue": "Molotow", "description": "punk"},
            text="Toll, sound wie Tocotronic. Aber EDM hasse ich.",
        ),
        llm=fake_llm,
    )

    u = db_session.query(User).filter_by(id="local").one()
    assert u.taste_facets["concerts"]["artists"]["Tocotronic"] == 0.3
    assert u.taste_facets["concerts"]["artists"]["Existing"] == 0.5
    assert u.taste_facets["concerts"]["disliked.genres"]["edm"] == 1.0


def test_extractor_ignores_updates_with_unknown_category(db_session):
    from app.db.models import User
    u = User(id="local", taste_facets={})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.return_value.facet_updates = [
        _fu("nonsense", "artists", "X", 0.5),
        _fu("concerts", "artists", "Y", 0.5),
    ]

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "t", "venue": "v", "description": "d"},
            text="ok",
        ),
        llm=fake_llm,
    )

    u = db_session.query(User).filter_by(id="local").one()
    assert "nonsense" not in u.taste_facets
    assert u.taste_facets["concerts"]["artists"]["Y"] == 0.5


def test_extractor_llm_failure_is_swallowed(db_session, caplog):
    from app.db.models import User
    u = User(id="local", taste_facets={})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("boom")

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "t", "venue": "v", "description": "d"},
            text="ok",
        ),
        llm=fake_llm,
    )

    assert "comment extractor failed" in caplog.text.lower()
    u = db_session.query(User).filter_by(id="local").one()
    assert u.taste_facets == {}


def _fu(category: str, field: str, key: str, delta: float):
    from app.agent.comment_extractor import FacetUpdate
    return FacetUpdate(category=category, field=field, key=key, delta=delta)
