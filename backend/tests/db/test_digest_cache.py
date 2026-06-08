from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import digest_cache as _dc, user as _user  # noqa: F401
from app.db.models.digest_cache import DigestCache
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()


def test_digest_cache_creation(db_session):
    _seed(db_session)
    d = DigestCache(
        id="dig_1", user_id="local", date=date(2026, 6, 8),
        picks=[{"event_id": "evt_1", "justification": "..."}],
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    assert d.picks == [{"event_id": "evt_1", "justification": "..."}]
    assert isinstance(d.generated_at, datetime)


def test_digest_cache_unique_per_user_date(db_session):
    _seed(db_session)
    db_session.add(DigestCache(id="dig_1", user_id="local", date=date(2026, 6, 8), picks=[]))
    db_session.commit()
    db_session.add(DigestCache(id="dig_2", user_id="local", date=date(2026, 6, 8), picks=[]))
    with pytest.raises(IntegrityError):
        db_session.commit()
