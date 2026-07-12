"""UTCDateTime column type — round-trip semantics on SQLite.

Reproduces the +Xh drift bug that motivated the type: SQLAlchemy on SQLite
silently strips tzinfo from tz-aware datetimes, so a Berlin-shipped
`19:00 Europe/Berlin` ended up stored as `19:00` naive and later labeled
UTC downstream. UTCDateTime pins the write side to UTC and re-attaches
tzinfo on read.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import StatementError

from app.db.models.event import Event


_BERLIN = ZoneInfo("Europe/Berlin")


def _kwargs(**overrides):
    base = dict(
        id="evt_1",
        external_id="ext_1",
        source="eventim",
        title="Orgelkonzert",
        description="Wolfgang Capek",
        summary=None,
        start_datetime=datetime(2026, 7, 15, 19, 0, tzinfo=_BERLIN),
        end_datetime=None,
        venue_name="Hauptkirche",
        venue_address=None,
        latitude=None,
        longitude=None,
        category="concerts",
        tags=[],
        price_min=None,
        price_max=None,
        is_free=False,
        currency="EUR",
        image_url=None,
        source_url="https://eventim.de/x",
        raw_data={},
    )
    base.update(overrides)
    return base


def test_berlin_input_roundtrips_as_utc_instant(db_session):
    """A Berlin 19:00 event stored and re-read yields 17:00 UTC — the same
    absolute instant, not the wall-clock 19:00 that used to leak through."""
    db_session.add(Event(**_kwargs()))
    db_session.commit()

    e = db_session.get(Event, "evt_1")
    assert e.start_datetime.tzinfo is not None
    assert e.start_datetime.utcoffset() == timezone.utc.utcoffset(None)
    # 19:00 Berlin CEST = 17:00 UTC
    assert e.start_datetime == datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc)


def test_utc_input_roundtrips_unchanged(db_session):
    """A UTC-shipping adapter (ticketmaster, eventbrite) still round-trips."""
    utc_start = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    db_session.add(Event(**_kwargs(start_datetime=utc_start)))
    db_session.commit()

    e = db_session.get(Event, "evt_1")
    assert e.start_datetime == utc_start


def test_naive_datetime_is_rejected(db_session):
    """UTCDateTime refuses naive datetimes so silent tz mistakes surface
    at write time instead of drifting into the display."""
    naive = datetime(2026, 7, 15, 19, 0)  # no tzinfo
    db_session.add(Event(**_kwargs(start_datetime=naive)))
    # SQLAlchemy wraps the type-decorator's ValueError in a StatementError.
    with pytest.raises(StatementError, match="naive datetime"):
        db_session.commit()


def test_end_datetime_none_is_preserved(db_session):
    db_session.add(Event(**_kwargs(end_datetime=None)))
    db_session.commit()
    e = db_session.get(Event, "evt_1")
    assert e.end_datetime is None
