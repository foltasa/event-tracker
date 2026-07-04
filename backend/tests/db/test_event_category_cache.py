from datetime import datetime

from app.db.models.event_category_cache import EventCategoryCache


def test_insert_and_query(db_session):
    row = EventCategoryCache(
        content_hash="deadbeef",
        category="theater",
        model="google/gemini-2.0-flash",
    )
    db_session.add(row)
    db_session.commit()

    fetched = (
        db_session.query(EventCategoryCache)
        .filter_by(content_hash="deadbeef")
        .one()
    )
    assert fetched.category == "theater"
    assert fetched.model == "google/gemini-2.0-flash"
    assert isinstance(fetched.created_at, datetime)


def test_content_hash_is_primary_key(db_session):
    db_session.add(EventCategoryCache(
        content_hash="h1", category="concerts", model="m1",
    ))
    db_session.commit()

    # Second insert with same hash should raise IntegrityError on commit
    import pytest
    from sqlalchemy.exc import IntegrityError
    db_session.add(EventCategoryCache(
        content_hash="h1", category="theater", model="m2",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unknown_is_allowed(db_session):
    """Cache stores literal 'unknown' when LLM cannot decide."""
    db_session.add(EventCategoryCache(
        content_hash="h_unknown", category="unknown", model="m",
    ))
    db_session.commit()
    fetched = db_session.query(EventCategoryCache).filter_by(content_hash="h_unknown").one()
    assert fetched.category == "unknown"
