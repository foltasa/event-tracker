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
