import pytest

from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], about_me="x",
             taste_summary="loves jazz")
    db_session.add(u)
    db_session.commit()
    return u


def test_get_profile(client, user):
    r = client.get("/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["city"] == "Hamburg"
    assert body["interest_tags"] == ["music"]
    assert body["taste_summary"] == "loves jazz"


def test_put_profile_updates_fields(client, user, db_session):
    r = client.put("/profile", json={"interest_tags": ["music", "tech"], "about_me": "new"})
    assert r.status_code == 200
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.interest_tags == ["music", "tech"]
    assert fresh.about_me == "new"


def test_post_onboard_creates_when_missing(client, db_session):
    r = client.post("/profile/onboard", json={"interest_tags": ["arts"], "about_me": "hi"})
    assert r.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.interest_tags == ["arts"]
    assert u.about_me == "hi"


def test_post_onboard_idempotent_updates_existing(client, user, db_session):
    r = client.post("/profile/onboard", json={"interest_tags": ["tech"]})
    assert r.status_code == 200
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.interest_tags == ["tech"]


def test_get_profile_settings_default_auto_recommendations_true(client, user):
    body = client.get("/profile").json()
    assert body["settings"]["auto_recommendations_enabled"] is True


def test_put_profile_settings_persists_flag(client, user, db_session):
    r = client.put("/profile/settings", json={"auto_recommendations_enabled": False})
    assert r.status_code == 200
    assert r.json()["settings"]["auto_recommendations_enabled"] is False
    body = client.get("/profile").json()
    assert body["settings"]["auto_recommendations_enabled"] is False


def test_put_profile_settings_partial_update_keeps_other_keys(client, user, db_session):
    client.put("/profile/settings", json={"auto_recommendations_enabled": False})
    r = client.put("/profile/settings", json={"auto_recommendations_enabled": True})
    assert r.json()["settings"]["auto_recommendations_enabled"] is True
