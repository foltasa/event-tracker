from unittest.mock import patch

from app.db.models import User


def _seed(db, **kwargs):
    u = User(id="local", **kwargs)
    db.add(u)
    db.commit()
    return u


def test_get_about_me_returns_defaults_for_fresh_user(client, db_session):
    _seed(db_session)
    res = client.get("/about-me")
    assert res.status_code == 200
    body = res.json()
    assert body["active_categories"] is None
    assert body["taste_facets"] == {}
    assert body["taste_summary"] is None


def test_put_about_me_activates_categories_and_sets_facets(client, db_session):
    _seed(db_session)
    payload = {
        "active_categories": ["concerts", "theater"],
        "taste_facets": {
            "concerts": {"artists": {"Die Sterne": 0.8}, "genres": {"punk": 0.8}},
        },
        "taste_summary": "prefers small venues",
    }
    res = client.put("/about-me", json=payload)
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts", "theater"]
    assert u.taste_facets["concerts"]["artists"]["Die Sterne"] == 0.8
    assert u.taste_summary == "prefers small venues"


def test_put_about_me_rejects_unknown_category(client, db_session):
    _seed(db_session)
    res = client.put("/about-me", json={"active_categories": ["nonsense"]})
    assert res.status_code == 422


def test_put_about_me_preserves_omitted_fields(client, db_session):
    _seed(
        db_session,
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"A": 0.5}}},
        taste_summary="old",
    )
    res = client.put("/about-me", json={"taste_summary": "new"})
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts"]
    assert u.taste_facets == {"concerts": {"artists": {"A": 0.5}}}
    assert u.taste_summary == "new"


def test_deselecting_a_category_preserves_its_facets(client, db_session):
    _seed(
        db_session,
        active_categories=["concerts", "theater"],
        taste_facets={
            "concerts": {"artists": {"Die Sterne": 0.8}},
            "theater": {"venues": {"Thalia": 0.8}},
        },
    )
    res = client.put("/about-me", json={"active_categories": ["concerts"]})
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts"]
    # Deselected category's facets stay in the DB.
    assert u.taste_facets["theater"]["venues"]["Thalia"] == 0.8


def test_notes_field_triggers_extractor(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes_about_me.settings.comment_extractor_enabled", True)
    db_session.add(User(id="local"))
    db_session.commit()

    payload = {
        "active_categories": ["concerts"],
        "taste_facets": {
            "concerts": {
                "artists": {"Die Sterne": 0.8},
                "notes": "small venues only, no EDM",
            }
        },
    }
    with patch("app.api.routes_about_me.extract_and_apply") as m:
        res = client.put("/about-me", json=payload)
    assert res.status_code == 200
    calls = [c for c in m.call_args_list if c.kwargs.get("input_", None)]
    # One call per category that carries a non-empty "notes" field.
    assert len(calls) == 1


def test_about_me_notes_do_not_schedule_extractor_when_disabled(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes_about_me.settings.comment_extractor_enabled", False)

    db_session.add(User(id="local", active_categories=["concerts"], taste_facets={}))
    db_session.commit()

    called = {"n": 0}

    def fake_extract_and_apply(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr("app.api.routes_about_me.extract_and_apply", fake_extract_and_apply)

    r = client.put("/about-me", json={
        "active_categories": ["concerts"],
        "taste_facets": {"concerts": {"notes": "I love late-night piano concerts"}},
    })
    assert r.status_code == 200
    assert called["n"] == 0
