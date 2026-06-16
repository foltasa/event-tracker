from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.appointment import AppointmentCreate, AppointmentUpdate


def _dt(h: int, m: int = 0) -> datetime:
    return datetime(2026, 6, 16, h, m, tzinfo=timezone.utc)


def test_all_day_payload_valid():
    p = AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=None, end_at=None)
    assert p.title == "X"


def test_open_end_payload_valid():
    p = AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=_dt(9), end_at=None)
    assert p.start_at == _dt(9)


def test_timed_payload_valid():
    p = AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=_dt(9), end_at=_dt(10))
    assert p.end_at == _dt(10)


def test_only_end_at_set_is_rejected():
    with pytest.raises(ValidationError):
        AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=None, end_at=_dt(10))


def test_end_at_not_after_start_at_same_day_rejected():
    with pytest.raises(ValidationError):
        AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=_dt(10), end_at=_dt(10))
    with pytest.raises(ValidationError):
        AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=_dt(10), end_at=_dt(9))


def test_cross_midnight_allowed_when_end_at_is_next_day():
    end = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc)
    p = AppointmentCreate(title="X", day=date(2026, 6, 16), start_at=_dt(22), end_at=end)
    assert p.end_at == end


def test_update_validators_only_when_both_present():
    # Only title in patch is fine
    p = AppointmentUpdate(title="X")
    assert p.title == "X"
    # Same validators when start/end fields are supplied
    with pytest.raises(ValidationError):
        AppointmentUpdate(start_at=None, end_at=_dt(10))
