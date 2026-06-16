import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import asc, nulls_first

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Appointment as AppointmentModel
from app.schemas.appointment import Appointment, AppointmentCreate, AppointmentUpdate, AppointmentsResponse

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


@router.get("", response_model=AppointmentsResponse)
def list_appointments(
    db: DbSession,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
) -> AppointmentsResponse:
    user_id = get_current_user_id()
    if from_ is None:
        from_ = _today_utc() - timedelta(days=90)
    if to is None:
        to = _today_utc() + timedelta(days=90)
    rows = (
        db.query(AppointmentModel)
        .filter(AppointmentModel.user_id == user_id)
        .filter(AppointmentModel.day >= from_)
        .filter(AppointmentModel.day <= to)
        .order_by(asc(AppointmentModel.day), nulls_first(asc(AppointmentModel.start_at)))
        .all()
    )
    return AppointmentsResponse(appointments=[Appointment.model_validate(r, from_attributes=True) for r in rows])


@router.post("", response_model=Appointment)
def create_appointment(payload: AppointmentCreate, db: DbSession) -> Appointment:
    user_id = get_current_user_id()
    row = AppointmentModel(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=payload.title,
        day=payload.day,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Appointment.model_validate(row, from_attributes=True)


@router.patch("/{appointment_id}", response_model=Appointment)
def update_appointment(
    appointment_id: str, payload: AppointmentUpdate, db: DbSession,
) -> Appointment:
    user_id = get_current_user_id()
    row = db.query(AppointmentModel).filter_by(id=appointment_id, user_id=user_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="appointment not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return Appointment.model_validate(row, from_attributes=True)


@router.delete("/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: str, db: DbSession) -> Response:
    user_id = get_current_user_id()
    row = db.query(AppointmentModel).filter_by(id=appointment_id, user_id=user_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="appointment not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
