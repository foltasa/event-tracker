from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import event as _event  # noqa: F401
from app.db.models.event import Event


def _event_kwargs(**overrides):
    base = dict(
        id="evt_1",
        external_id="eb_12345",
        source="eventbrite",
        title="Jazz Night",
        description="Trio set",
        summary="Doors 20:00",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc),
        venue_name="Mojo Club",
        venue_address="Reeperbahn 1",
        latitude=53.5497,
        longitude=9.9657,
        category="music",
        tags=["jazz", "live"],
        price_min=18.0,
        price_max=24.0,
        is_free=False,
        currency="EUR",
        image_url="https://example.com/img.jpg",
        source_url="https://eventbrite.de/e/12345",
        raw_data={"id": "12345"},
    )
    base.update(overrides)
    return base


def test_event_creation(db_session):
    e = Event(**_event_kwargs())
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    assert e.is_active is True
    assert e.currency == "EUR"
    assert isinstance(e.ingested_at, datetime)


def test_event_unique_external_id_source(db_session):
    db_session.add(Event(**_event_kwargs(id="evt_a")))
    db_session.commit()
    db_session.add(Event(**_event_kwargs(id="evt_b")))  # same (external_id, source)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_event_allows_same_external_id_different_source(db_session):
    db_session.add(Event(**_event_kwargs(id="evt_a", source="eventbrite")))
    db_session.add(Event(**_event_kwargs(id="evt_b", source="ticketmaster")))
    db_session.commit()  # no error
