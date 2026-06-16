from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from app.schemas.common import _JsonBase


def _validate_time_pair(
    start_at: datetime | None,
    end_at: datetime | None,
) -> None:
    if start_at is None and end_at is not None:
        raise ValueError("end_at requires start_at")
    if start_at is not None and end_at is not None:
        # Reject end <= start when both fall on the same calendar day.
        if end_at.date() == start_at.date() and end_at <= start_at:
            raise ValueError("end_at must be after start_at on the same day")


class Appointment(_JsonBase):
    id: str
    title: str
    day: date
    start_at: datetime | None
    end_at: datetime | None
    created_at: datetime


class AppointmentCreate(_JsonBase):
    title: str = Field(min_length=1)
    day: date
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def _check_times(self) -> Self:
        _validate_time_pair(self.start_at, self.end_at)
        return self


class AppointmentUpdate(_JsonBase):
    title: str | None = Field(default=None, min_length=1)
    day: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def _check_times(self) -> Self:
        # Only enforce when at least one of (start_at, end_at) was supplied in
        # the patch; otherwise leave time fields untouched.
        if "start_at" in self.model_fields_set or "end_at" in self.model_fields_set:
            _validate_time_pair(self.start_at, self.end_at)
        return self


class AppointmentsResponse(_JsonBase):
    appointments: list[Appointment] = Field(default_factory=list)
