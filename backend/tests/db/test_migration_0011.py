"""Migration 0011 — DST-aware shift from Berlin-local to UTC and back."""
from app.db.migrations.migration_0011_helpers import (
    _localize_berlin_to_utc,
    _utc_to_berlin_naive,
)


def test_summer_time_shifts_by_two_hours():
    """CEST (UTC+2) — 19:00 Berlin ⇒ 17:00 UTC."""
    assert _localize_berlin_to_utc("2026-07-15 19:00:00") == "2026-07-15 17:00:00"


def test_winter_time_shifts_by_one_hour():
    """CET (UTC+1) — 20:00 Berlin ⇒ 19:00 UTC."""
    assert _localize_berlin_to_utc("2026-12-10 20:00:00") == "2026-12-10 19:00:00"


def test_iso_t_separator_is_accepted():
    """Rows written by SQLAlchemy sometimes use the 'T' separator."""
    assert _localize_berlin_to_utc("2026-07-15T19:00:00") == "2026-07-15 17:00:00"


def test_none_and_empty_pass_through():
    assert _localize_berlin_to_utc(None) is None
    assert _localize_berlin_to_utc("") == ""


def test_already_aware_utc_input_is_preserved():
    """If a row was stored with an offset (Postgres path), the upgrade
    treats the UTC instant as authoritative."""
    assert _localize_berlin_to_utc("2026-07-15 19:00:00+00:00") == "2026-07-15 19:00:00"


def test_downgrade_is_inverse_of_upgrade():
    """Round-trip: upgrade then downgrade recovers the original naive string."""
    original = "2026-07-15 19:00:00"
    shifted = _localize_berlin_to_utc(original)
    assert _utc_to_berlin_naive(shifted) == original
