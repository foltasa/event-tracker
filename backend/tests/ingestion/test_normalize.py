from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.ingestion.normalize import NormalizedEvent

BERLIN = timezone(timedelta(hours=2))


def _kwargs(**overrides):
    base = dict(
        external_id="eb_1", source="eventbrite", title="t",
        description="d", summary="s",
        start_datetime=datetime(2026, 6, 14, 20, 0, tzinfo=BERLIN),
        end_datetime=datetime(2026, 6, 14, 23, 0, tzinfo=BERLIN),
        venue_name="v", venue_address="a", latitude=53.5, longitude=9.9,
        category="music", tags=["jazz"],
        price_min=10.0, price_max=20.0, is_free=False, currency="EUR",
        image_url="https://x/i", source_url="https://x/e/1", raw_data={"k": "v"},
    )
    base.update(overrides)
    return base


def test_normalized_event_minimal():
    e = NormalizedEvent(**_kwargs())
    assert e.category == "music"
    assert e.currency == "EUR"


def test_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(start_datetime=datetime(2026, 6, 14, 20, 0)))


def test_rejects_unknown_category():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(category="nope"))


def test_rejects_empty_external_id():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(external_id=""))


def test_rejects_empty_source_url():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(source_url=""))


def test_rejects_price_min_gt_max():
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(price_min=30.0, price_max=20.0))


def test_is_free_requires_zero_or_null_prices():
    # is_free=True with non-zero prices → error
    with pytest.raises(ValidationError):
        NormalizedEvent(**_kwargs(is_free=True, price_min=10.0, price_max=20.0))
    # is_free=True with None prices → ok
    e = NormalizedEvent(**_kwargs(is_free=True, price_min=None, price_max=None))
    assert e.is_free is True
    # is_free=True with 0 prices → ok
    e2 = NormalizedEvent(**_kwargs(is_free=True, price_min=0.0, price_max=0.0))
    assert e2.is_free is True


# ---------------------------------------------------------------------------
# Upsert + deactivation tests (added in ingestion pipeline task)
# ---------------------------------------------------------------------------
from app.ingestion.normalize import UpsertReport, deactivate_past_events, upsert_events  # noqa: E402
from datetime import timedelta


def _normed_event(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="src_001",
        source="eventbrite",
        title="Test Event",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=BERLIN),
        category="music",
        is_free=False,
        price_min=10.0,
        price_max=20.0,
        source_url="https://example.com/e/001",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_upsert_inserts_new_event(db_session):
    report = upsert_events(db_session, [_normed_event()])
    db_session.commit()
    assert report.inserted == 1
    assert report.updated == 0
    assert report.skipped == 0


def test_upsert_updates_existing_event(db_session):
    upsert_events(db_session, [_normed_event(title="Original")])
    db_session.commit()

    report = upsert_events(db_session, [_normed_event(title="Updated")])
    db_session.commit()

    assert report.inserted == 0
    assert report.updated == 1

    from app.db.models.event import Event
    ev = db_session.query(Event).filter_by(external_id="src_001", source="eventbrite").one()
    assert ev.title == "Updated"


def test_upsert_is_idempotent(db_session):
    events = [_normed_event()]
    upsert_events(db_session, events)
    db_session.commit()
    report = upsert_events(db_session, events)
    db_session.commit()

    from app.db.models.event import Event
    assert db_session.query(Event).count() == 1
    assert report.updated == 1


def test_upsert_handles_multiple_sources(db_session):
    report = upsert_events(db_session, [
        _normed_event(source="eventbrite", external_id="001"),
        _normed_event(source="ticketmaster", external_id="001"),
    ])
    db_session.commit()
    assert report.inserted == 2


def test_deactivate_past_events(db_session):
    now = datetime.now(tz=timezone.utc)
    past = _normed_event(external_id="past", start_datetime=now - timedelta(days=1))
    future = _normed_event(external_id="future", start_datetime=now + timedelta(days=1))

    upsert_events(db_session, [past, future])
    db_session.commit()

    count = deactivate_past_events(db_session)
    db_session.commit()

    from app.db.models.event import Event
    past_ev = db_session.query(Event).filter_by(external_id="past").one()
    future_ev = db_session.query(Event).filter_by(external_id="future").one()

    assert count == 1
    assert past_ev.is_active is False
    assert future_ev.is_active is True


def test_upsert_skips_on_error(db_session):
    class _Bad:
        external_id = "bad"
        source = "test"
        # model_dump does not exist → AttributeError caught by except Exception
        def __getattr__(self, name):
            raise AttributeError(f"no attr {name}")

    good = _normed_event()
    report = upsert_events(db_session, [_Bad(), good])
    db_session.commit()
    assert report.skipped == 1
    assert report.inserted == 1


def test_deactivate_does_not_double_count_already_inactive(db_session):
    now = datetime.now(tz=timezone.utc)
    past = _normed_event(external_id="past", start_datetime=now - timedelta(days=1))
    upsert_events(db_session, [past])
    db_session.commit()

    deactivate_past_events(db_session)
    db_session.commit()
    count = deactivate_past_events(db_session)
    db_session.commit()

    assert count == 0
