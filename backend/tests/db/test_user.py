from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

# Import all models so Base.metadata is populated for the fixture.
from app.db.models import user as _user  # noqa: F401
from app.db.models.user import User


def test_user_creation_with_defaults(db_session):
    u = User(id="local", interest_tags=["music", "tech"], settings={})
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    assert u.id == "local"
    assert u.city == "Hamburg"
    assert u.interest_tags == ["music", "tech"]
    assert u.about_me is None
    assert u.taste_summary is None
    assert u.settings == {}
    assert isinstance(u.created_at, datetime)
    assert isinstance(u.updated_at, datetime)


def test_user_id_is_primary_key(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()
    db_session.add(User(id="local", interest_tags=[], settings={}))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_user_has_taste_centroid_and_dirty_flag(db_session):
    from app.db.models import User
    u = User(id="local", interest_tags=["music"])
    db_session.add(u)
    db_session.commit()
    fresh = db_session.query(User).filter_by(id="local").first()
    assert fresh.taste_summary_dirty is True  # default true => first read triggers initial summary
    assert fresh.taste_centroid is None


def test_user_taste_centroid_roundtrip(db_session):
    from app.db.models import User
    u = User(id="local", interest_tags=[], taste_centroid=[0.1, 0.2, 0.3])
    db_session.add(u)
    db_session.commit()
    fresh = db_session.query(User).filter_by(id="local").first()
    assert fresh.taste_centroid == [0.1, 0.2, 0.3]
