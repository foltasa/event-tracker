import pytest

from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], about_me="x",
             taste_summary="loves jazz", taste_summary_dirty=False)
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


def test_put_profile_updates_and_marks_dirty(client, user, db_session):
    r = client.put("/profile", json={"interest_tags": ["music", "tech"], "about_me": "new"})
    assert r.status_code == 200
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.interest_tags == ["music", "tech"]
    assert fresh.about_me == "new"
    assert fresh.taste_summary_dirty is True


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
