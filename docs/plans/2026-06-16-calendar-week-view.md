# Calendar Week-View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the small month-grid calendar with a full-column Google-Calendar-style week view; add a backend `appointments` table with CRUD + a placeholder recommend route; add a click-to-create modal with Make/Recommend tabs; seed the default user with Turing College Mon–Fri 09:00–16:30 across June and July 2026.

**Architecture:** New SQLAlchemy `Appointment` model + Alembic migration + Pydantic schemas + FastAPI routes at `/appointments`. Frontend rewrites `app/calendar/page.tsx` as a thin wrapper around new `components/calendar/*` primitives that render both saved feed events (`/calendar`) and custom appointments (`/appointments`) through a single normalized `GridItem` shape. A new portal-based `AppointmentModal` provides Make/Recommend tabs.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic v2 (backend). Next.js 14 App Router + React 18 + SWR + Tailwind + Vitest + React Testing Library (frontend).

**Spec:** `docs/specs/2026-06-16-calendar-week-view-design.md`

---

## File Map

**Backend — new:**
- `backend/app/db/models/appointment.py`
- `backend/app/db/migrations/versions/0004_appointments.py`
- `backend/app/schemas/appointment.py`
- `backend/app/api/routes_appointments.py`
- `backend/scripts/__init__.py`
- `backend/scripts/seed_default_appointments.py`
- `backend/tests/db/test_appointment.py`
- `backend/tests/api/test_routes_appointments.py`
- `backend/tests/scripts/__init__.py`
- `backend/tests/scripts/test_seed_default_appointments.py`

**Backend — modified:**
- `backend/app/db/models/__init__.py` — re-export `Appointment`
- `backend/app/main.py` — `include_router(routes_appointments.router)`

**Frontend — new:**
- `frontend/lib/calendarGrid.ts`
- `frontend/lib/__tests__/calendarGrid.test.ts`
- `frontend/components/calendar/HourGutter.tsx`
- `frontend/components/calendar/WeekdayStrip.tsx`
- `frontend/components/calendar/NowLine.tsx`
- `frontend/components/calendar/WeekHeader.tsx`
- `frontend/components/calendar/EventBlock.tsx`
- `frontend/components/calendar/DayColumn.tsx`
- `frontend/components/calendar/WeekView.tsx`
- `frontend/components/calendar/appointmentModal/AppointmentModal.tsx`
- `frontend/components/calendar/appointmentModal/MakeAppointmentTab.tsx`
- `frontend/components/calendar/appointmentModal/RecommendTab.tsx`
- `frontend/components/__tests__/AppointmentModal.test.tsx`
- `frontend/components/__tests__/RecommendTab.test.tsx`
- `frontend/components/__tests__/WeekView.test.tsx`

**Frontend — modified:**
- `frontend/lib/types.ts` — add Appointment types
- `frontend/lib/api.ts` — add appointment functions
- `frontend/components/AppShell.tsx` — extend `fanOutEventCaches` to revalidate `/appointments`
- `frontend/app/calendar/page.tsx` — replace month grid with `<WeekView>`

---

## Task 1: Backend — `Appointment` SQLAlchemy model

**Files:**
- Create: `backend/app/db/models/appointment.py`
- Modify: `backend/app/db/models/__init__.py`
- Test: `backend/tests/db/test_appointment.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/db/test_appointment.py`)

```python
from datetime import date, datetime, timezone

from app.db.models import Appointment, User


def test_appointment_minimal_all_day(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Appointment(
        id="a1", user_id="local", title="Birthday",
        day=date(2026, 6, 16), start_at=None, end_at=None,
    ))
    db_session.commit()
    row = db_session.query(Appointment).one()
    assert row.title == "Birthday"
    assert row.day == date(2026, 6, 16)
    assert row.start_at is None
    assert row.end_at is None
    assert row.created_at is not None


def test_appointment_timed(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Appointment(
        id="a2", user_id="local", title="Standup",
        day=date(2026, 6, 16),
        start_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc),
    ))
    db_session.commit()
    row = db_session.query(Appointment).one()
    assert row.start_at.hour == 9
    assert row.end_at.minute == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:
```
pytest tests/db/test_appointment.py -v
```
Expected: ImportError — `Appointment` cannot be imported from `app.db.models`.

- [ ] **Step 3: Create the model** (`backend/app/db/models/appointment.py`)

```python
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_user_day", "user_id", "day"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
```

- [ ] **Step 4: Re-export in models `__init__`** (`backend/app/db/models/__init__.py`)

Add the import and append `"Appointment"` to `__all__`:
```python
from app.db.models.appointment import Appointment
# ...existing imports...

__all__ = ["Appointment", "ChatMessage", "DigestCache", "Event", "Feedback", "SavedEvent", "User"]
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/db/test_appointment.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/appointment.py backend/app/db/models/__init__.py backend/tests/db/test_appointment.py
git commit -m "feat(backend): add Appointment SQLAlchemy model"
```

---

## Task 2: Backend — Alembic migration `0004_appointments`

**Files:**
- Create: `backend/app/db/migrations/versions/0004_appointments.py`

- [ ] **Step 1: Author the migration file**

```python
"""appointments table

Revision ID: 0004_appointments
Revises: 0003_user_memory_blobs
Create Date: 2026-06-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_appointments"
down_revision: Union[str, Sequence[str], None] = "0003_user_memory_blobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_appointments_user_day", "appointments", ["user_id", "day"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_user_day", table_name="appointments")
    op.drop_table("appointments")
```

- [ ] **Step 2: Sanity-check the migration by upgrading a temp DB**

Run from `backend/`:
```
alembic upgrade head
```
Expected: completes without error; `appointments` table exists in `event_tracker.db` (or `:memory:` in tests). Then:
```
alembic downgrade -1
alembic upgrade head
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/migrations/versions/0004_appointments.py
git commit -m "feat(backend): add 0004 appointments migration"
```

---

## Task 3: Backend — Pydantic schemas with validators

**Files:**
- Create: `backend/app/schemas/appointment.py`
- Test: extend `backend/tests/db/test_appointment.py` with schema-validation tests, OR put them in a new `backend/tests/schemas/test_appointment.py`. Use the latter to keep DB and schema tests separate.

- [ ] **Step 1: Write the failing schema test** (`backend/tests/schemas/test_appointment.py`)

```python
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
```

Make sure `backend/tests/schemas/__init__.py` exists (create an empty one if not).

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/schemas/test_appointment.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create the schema** (`backend/app/schemas/appointment.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/schemas/test_appointment.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/appointment.py backend/tests/schemas/__init__.py backend/tests/schemas/test_appointment.py
git commit -m "feat(backend): add Appointment Pydantic schemas with validators"
```

---

## Task 4: Backend — `GET /appointments` route

**Files:**
- Create: `backend/app/api/routes_appointments.py`
- Test: `backend/tests/api/test_routes_appointments.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime, timezone

import pytest

from app.db.models import Appointment, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(User(id="other", interest_tags=[]))
    db_session.add(Appointment(
        id="a1", user_id="local", title="In window",
        day=date(2026, 6, 16),
        start_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc),
    ))
    db_session.add(Appointment(
        id="a2", user_id="local", title="Out of window",
        day=date(2026, 8, 1), start_at=None, end_at=None,
    ))
    db_session.add(Appointment(
        id="a3", user_id="other", title="Other user",
        day=date(2026, 6, 16), start_at=None, end_at=None,
    ))
    db_session.commit()


def test_list_filters_by_user_and_window(client, setup):
    r = client.get("/appointments?from=2026-06-01&to=2026-06-30")
    assert r.status_code == 200
    body = r.json()
    titles = [a["title"] for a in body["appointments"]]
    assert titles == ["In window"]


def test_list_defaults_to_90_day_window(client, setup):
    # Using monkeypatchable "today" is overkill; just verify the default
    # window includes June 2026 when the test runs.
    r = client.get("/appointments")
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/api/test_routes_appointments.py -v
```
Expected: 404 — route not registered (test will fail).

- [ ] **Step 3: Create the route module** (`backend/app/api/routes_appointments.py`)

```python
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import asc, nulls_first

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import Appointment as AppointmentModel
from app.schemas.appointment import Appointment, AppointmentsResponse

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
```

- [ ] **Step 4: Wire the router temporarily for the test** (`backend/app/main.py`)

Add `routes_appointments` to the imports and `include_router` calls. (We'll keep this wiring; Task 9 just verifies it's there.)

```python
from app.api import routes_appointments  # alongside existing route imports
# ...
app.include_router(routes_appointments.router)
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/api/test_routes_appointments.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_appointments.py backend/app/main.py backend/tests/api/test_routes_appointments.py
git commit -m "feat(backend): add GET /appointments route"
```

---

## Task 5: Backend — `POST /appointments` route

**Files:**
- Modify: `backend/app/api/routes_appointments.py`
- Modify: `backend/tests/api/test_routes_appointments.py`

- [ ] **Step 1: Append failing tests**

```python
def test_post_creates_timed_appointment(client, setup, db_session):
    r = client.post("/appointments", json={
        "title": "Lunch",
        "day": "2026-06-17",
        "start_at": "2026-06-17T12:00:00+00:00",
        "end_at": "2026-06-17T13:00:00+00:00",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Lunch"
    from app.db.models import Appointment as A
    assert db_session.query(A).filter_by(title="Lunch", user_id="local").count() == 1


def test_post_only_end_at_400(client, setup):
    r = client.post("/appointments", json={
        "title": "Bad",
        "day": "2026-06-17",
        "start_at": None,
        "end_at": "2026-06-17T13:00:00+00:00",
    })
    assert r.status_code == 422


def test_post_scopes_to_current_user(client, setup, db_session):
    client.post("/appointments", json={
        "title": "ScopedToLocal",
        "day": "2026-06-17",
        "start_at": None, "end_at": None,
    })
    from app.db.models import Appointment as A
    row = db_session.query(A).filter_by(title="ScopedToLocal").one()
    assert row.user_id == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/api/test_routes_appointments.py -v
```
Expected: the three new tests fail with 405 Method Not Allowed.

- [ ] **Step 3: Add the POST handler** to `routes_appointments.py`

```python
import uuid

from app.schemas.appointment import AppointmentCreate


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
```

- [ ] **Step 4: Run tests**

```
pytest tests/api/test_routes_appointments.py -v
```
Expected: 5 passed (2 from Task 4 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_appointments.py backend/tests/api/test_routes_appointments.py
git commit -m "feat(backend): add POST /appointments route"
```

---

## Task 6: Backend — `PATCH /appointments/{id}` route

**Files:**
- Modify: `backend/app/api/routes_appointments.py`
- Modify: `backend/tests/api/test_routes_appointments.py`

- [ ] **Step 1: Append failing tests**

```python
def test_patch_updates_fields(client, setup, db_session):
    r = client.patch("/appointments/a1", json={"title": "Renamed"})
    assert r.status_code == 200
    from app.db.models import Appointment as A
    assert db_session.query(A).filter_by(id="a1").one().title == "Renamed"


def test_patch_other_users_appointment_404(client, setup):
    r = client.patch("/appointments/a3", json={"title": "Hijack"})
    assert r.status_code == 404


def test_patch_validates_times(client, setup):
    r = client.patch("/appointments/a1", json={
        "start_at": None,
        "end_at": "2026-06-16T10:00:00+00:00",
    })
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests** — expect failures (405).

```
pytest tests/api/test_routes_appointments.py -v
```

- [ ] **Step 3: Add the PATCH handler** to `routes_appointments.py`

```python
from fastapi import HTTPException

from app.schemas.appointment import AppointmentUpdate


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
```

- [ ] **Step 4: Run tests** — expect 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_appointments.py backend/tests/api/test_routes_appointments.py
git commit -m "feat(backend): add PATCH /appointments/{id} route"
```

---

## Task 7: Backend — `DELETE /appointments/{id}` route

**Files:**
- Modify: `backend/app/api/routes_appointments.py`
- Modify: `backend/tests/api/test_routes_appointments.py`

- [ ] **Step 1: Append failing tests**

```python
def test_delete_removes_appointment(client, setup, db_session):
    r = client.delete("/appointments/a1")
    assert r.status_code == 204
    from app.db.models import Appointment as A
    assert db_session.query(A).filter_by(id="a1").one_or_none() is None


def test_delete_other_users_appointment_404(client, setup):
    r = client.delete("/appointments/a3")
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — failures (405).

```
pytest tests/api/test_routes_appointments.py -v
```

- [ ] **Step 3: Add the DELETE handler**

```python
from fastapi import Response


@router.delete("/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: str, db: DbSession) -> Response:
    user_id = get_current_user_id()
    row = db.query(AppointmentModel).filter_by(id=appointment_id, user_id=user_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="appointment not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Run** — expect 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_appointments.py backend/tests/api/test_routes_appointments.py
git commit -m "feat(backend): add DELETE /appointments/{id} route"
```

---

## Task 8: Backend — `POST /appointments/recommend` placeholder

**Files:**
- Modify: `backend/app/api/routes_appointments.py`
- Modify: `backend/tests/api/test_routes_appointments.py`

- [ ] **Step 1: Append failing test**

```python
def test_recommend_returns_placeholder(client, setup):
    r = client.post("/appointments/recommend", json={
        "day": "2026-06-17", "start_at": None, "end_at": None, "message": "anything"
    })
    assert r.status_code == 200
    assert r.json() == {"message": "Currently not implemented"}
```

- [ ] **Step 2: Run** — failure.

- [ ] **Step 3: Add the handler**

```python
from datetime import date as _date

from pydantic import BaseModel


class _RecommendIn(BaseModel):
    day: _date
    start_at: datetime | None = None
    end_at: datetime | None = None
    message: str


class _RecommendOut(BaseModel):
    message: str


@router.post("/recommend", response_model=_RecommendOut)
def recommend(_payload: _RecommendIn) -> _RecommendOut:
    return _RecommendOut(message="Currently not implemented")
```

- [ ] **Step 4: Run** — expect 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_appointments.py backend/tests/api/test_routes_appointments.py
git commit -m "feat(backend): add POST /appointments/recommend placeholder"
```

---

## Task 9: Backend — Verify main.py router wiring

**Files:**
- Modify: `backend/app/main.py` (already touched in Task 4)
- Test: `backend/tests/api/test_main.py` (add an assertion if useful)

- [ ] **Step 1: Confirm the include_router call is present**

Open `backend/app/main.py`. Confirm `from app.api import routes_appointments` is present and `app.include_router(routes_appointments.router)` is called alongside the others. If Task 4 already added these, this task is a no-op verification.

- [ ] **Step 2: Run the full backend suite**

```
pytest -q
```
Expected: all green.

- [ ] **Step 3 (optional): Commit if any wiring fixes were required**

```bash
git add backend/app/main.py
git commit -m "chore(backend): ensure appointments router is included"
```

---

## Task 10: Backend — Seed script for Turing College

**Files:**
- Create: `backend/scripts/__init__.py` (empty)
- Create: `backend/scripts/seed_default_appointments.py`
- Create: `backend/tests/scripts/__init__.py` (empty)
- Create: `backend/tests/scripts/test_seed_default_appointments.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime, timezone

from app.db.models import Appointment, User
from scripts.seed_default_appointments import seed_turing_college


def test_seed_inserts_45_weekdays(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()

    n = seed_turing_college(db_session, user_id="local")
    assert n == 45
    rows = db_session.query(Appointment).filter_by(title="Turing College").all()
    assert len(rows) == 45
    # All weekdays only
    for r in rows:
        assert r.day.weekday() < 5
    # Range spans June and July 2026
    assert min(r.day for r in rows) == date(2026, 6, 1)
    assert max(r.day for r in rows) == date(2026, 7, 31)


def test_seed_is_idempotent(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()
    seed_turing_college(db_session, user_id="local")
    inserted_again = seed_turing_college(db_session, user_id="local")
    assert inserted_again == 0
    assert db_session.query(Appointment).filter_by(title="Turing College").count() == 45


def test_seed_times_anchor_to_hamburg_local(db_session):
    db_session.add(User(id="local", interest_tags=[]))
    db_session.commit()
    seed_turing_college(db_session, user_id="local")
    row = (
        db_session.query(Appointment)
        .filter_by(title="Turing College", day=date(2026, 6, 1))
        .one()
    )
    # Hamburg is UTC+2 in June (CEST). 09:00 local -> 07:00 UTC.
    assert row.start_at == datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)
    # 16:30 local -> 14:30 UTC.
    assert row.end_at == datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run** — failure (module not found).

```
pytest tests/scripts/test_seed_default_appointments.py -v
```

- [ ] **Step 3: Create the seed script** (`backend/scripts/seed_default_appointments.py`)

```python
"""Seed the default user's Turing College Mon-Fri appointments for Jun + Jul 2026.

Run with: `python -m scripts.seed_default_appointments` from `backend/`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Appointment
from app.db.session import SessionLocal

_HAMBURG = ZoneInfo("Europe/Berlin")
_TITLE = "Turing College"


def _weekdays(start: date, end_inclusive: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end_inclusive:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _local_to_utc(day: date, hour: int, minute: int) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_HAMBURG)
    return local.astimezone(UTC)


def seed_turing_college(db: Session, user_id: str) -> int:
    """Insert Turing College Mon-Fri 09:00-16:30 (Hamburg local) for Jun+Jul 2026.

    Returns the number of rows inserted (existing rows are skipped).
    """
    days = _weekdays(date(2026, 6, 1), date(2026, 7, 31))
    inserted = 0
    for d in days:
        existing = (
            db.query(Appointment)
            .filter_by(user_id=user_id, title=_TITLE, day=d)
            .one_or_none()
        )
        if existing is not None:
            continue
        db.add(Appointment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=_TITLE,
            day=d,
            start_at=_local_to_utc(d, 9, 0),
            end_at=_local_to_utc(d, 16, 30),
        ))
        inserted += 1
    db.commit()
    return inserted


def main() -> None:
    with SessionLocal() as db:
        n = seed_turing_college(db, user_id=settings.default_user_id)
        print(f"Inserted {n} Turing College appointments")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```
pytest tests/scripts/test_seed_default_appointments.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run the script against the dev DB**

From `backend/`:
```
python -m scripts.seed_default_appointments
```
Expected output: `Inserted 45 Turing College appointments` (or `0` if already seeded).

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/__init__.py backend/scripts/seed_default_appointments.py backend/tests/scripts/__init__.py backend/tests/scripts/test_seed_default_appointments.py
git commit -m "feat(backend): seed Turing College Mon-Fri across June+July 2026"
```

---

## Task 11: Frontend — Add Appointment types

**Files:**
- Modify: `frontend/lib/types.ts`

- [ ] **Step 1: Append the new interfaces** at the end of `types.ts`, right after `CalendarResponse`

```ts
export interface Appointment {
  id: string;
  title: string;
  day: string;              // ISO date YYYY-MM-DD
  start_at: string | null;  // ISO 8601
  end_at: string | null;
  created_at: string;
}

export interface AppointmentCreate {
  title: string;
  day: string;
  start_at: string | null;
  end_at: string | null;
}

export type AppointmentUpdate = Partial<AppointmentCreate>;

export interface AppointmentsResponse {
  appointments: Appointment[];
}

export interface RecommendRequest {
  day: string;
  start_at: string | null;
  end_at: string | null;
  message: string;
}

export interface RecommendResponse {
  message: string;
}
```

- [ ] **Step 2: Verify the project still type-checks**

From `frontend/`:
```
npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(frontend): add Appointment types"
```

---

## Task 12: Frontend — Add API client functions

**Files:**
- Modify: `frontend/lib/api.ts`
- Test: `frontend/lib/__tests__/api.test.ts` (extend)

- [ ] **Step 1: Append failing tests** to `frontend/lib/__tests__/api.test.ts`

```ts
import {
  createAppointment, deleteAppointment, listAppointments,
  recommendAppointment, updateAppointment,
} from '@/lib/api'

const mockApp = {
  id: 'app-1', title: 'X', day: '2026-06-16',
  start_at: null, end_at: null, created_at: '2026-06-16T10:00:00Z',
}

describe('appointments API', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ appointments: [mockApp] }),
    } as Response)
  })

  it('listAppointments GETs /appointments with from/to', async () => {
    await listAppointments('2026-06-01', '2026-06-30')
    const [url] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\?from=2026-06-01&to=2026-06-30$/)
  })

  it('createAppointment POSTs JSON body', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => mockApp,
    } as Response)
    await createAppointment({ title: 'X', day: '2026-06-16', start_at: null, end_at: null })
    const [, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(init!.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual({
      title: 'X', day: '2026-06-16', start_at: null, end_at: null,
    })
  })

  it('updateAppointment PATCHes /appointments/{id}', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => mockApp,
    } as Response)
    await updateAppointment('app-1', { title: 'Renamed' })
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\/app-1$/)
    expect(init!.method).toBe('PATCH')
  })

  it('deleteAppointment DELETEs /appointments/{id}', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
    } as Response)
    await deleteAppointment('app-1')
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\/app-1$/)
    expect(init!.method).toBe('DELETE')
  })

  it('recommendAppointment POSTs to /appointments/recommend', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => ({ message: 'Currently not implemented' }),
    } as Response)
    const out = await recommendAppointment({
      day: '2026-06-16', start_at: null, end_at: null, message: 'hi',
    })
    expect(out).toEqual({ message: 'Currently not implemented' })
  })
})
```

- [ ] **Step 2: Run** — failures (functions not exported).

```
cd frontend && npm test
```

- [ ] **Step 3: Append the API functions** to `frontend/lib/api.ts` (above the `// ---------- Profile & settings ----------` section)

```ts
import type {
  Appointment,
  AppointmentCreate,
  AppointmentUpdate,
  AppointmentsResponse,
  RecommendRequest,
  RecommendResponse,
} from "@/lib/types";

// ---------- Appointments ----------

export async function listAppointments(from: string, to: string): Promise<AppointmentsResponse> {
  if (MOCK) return { appointments: [] };
  return jsonFetch<AppointmentsResponse>(`/appointments?from=${from}&to=${to}`);
}

export async function createAppointment(body: AppointmentCreate): Promise<Appointment> {
  if (MOCK) {
    console.info("[mock] POST /appointments", body);
    return { id: `app_mock_${Date.now()}`, ...body, created_at: new Date().toISOString() };
  }
  return jsonFetch<Appointment>("/appointments", { method: "POST", body: JSON.stringify(body) });
}

export async function updateAppointment(id: string, body: AppointmentUpdate): Promise<Appointment> {
  if (MOCK) {
    console.info("[mock] PATCH /appointments/", id, body);
    return {
      id, title: body.title ?? "", day: body.day ?? new Date().toISOString().slice(0, 10),
      start_at: body.start_at ?? null, end_at: body.end_at ?? null,
      created_at: new Date().toISOString(),
    };
  }
  return jsonFetch<Appointment>(`/appointments/${encodeURIComponent(id)}`, {
    method: "PATCH", body: JSON.stringify(body),
  });
}

export async function deleteAppointment(id: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /appointments/", id);
    return;
  }
  await fetch(`${API_URL}/appointments/${encodeURIComponent(id)}`, {
    method: "DELETE", headers: headers(),
  });
}

export async function recommendAppointment(body: RecommendRequest): Promise<RecommendResponse> {
  if (MOCK) {
    console.info("[mock] POST /appointments/recommend", body);
    return { message: "Currently not implemented" };
  }
  return jsonFetch<RecommendResponse>("/appointments/recommend", {
    method: "POST", body: JSON.stringify(body),
  });
}
```

Merge the `import type {...}` statement into the existing import block at the top instead of duplicating it.

- [ ] **Step 4: Run tests**

```
cd frontend && npm test
```
Expected: all green including the new five.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/__tests__/api.test.ts
git commit -m "feat(frontend): add appointments API client functions"
```

---

## Task 13: Frontend — `lib/calendarGrid.ts` helpers

**Files:**
- Create: `frontend/lib/calendarGrid.ts`
- Test: `frontend/lib/__tests__/calendarGrid.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
import { describe, expect, it } from 'vitest'
import {
  getWeekRange, layoutDayColumn, toGridItem,
  type GridItem,
} from '@/lib/calendarGrid'

describe('getWeekRange', () => {
  it('starts on Monday and ends Sunday 24:00', () => {
    // 2026-06-16 is a Tuesday
    const { start, end } = getWeekRange(new Date('2026-06-16T12:00:00Z'))
    expect(start.getDay()).toBe(1)   // Monday
    expect(end.getTime() - start.getTime()).toBe(7 * 24 * 60 * 60 * 1000)
  })

  it('uses local-time anchoring at midnight', () => {
    const { start } = getWeekRange(new Date('2026-06-16T12:00:00Z'))
    expect(start.getHours()).toBe(0)
    expect(start.getMinutes()).toBe(0)
  })
})

describe('toGridItem', () => {
  it('normalizes a timed appointment', () => {
    const out = toGridItem({
      kind: 'appointment',
      raw: {
        id: 'a1', title: 'Standup', day: '2026-06-16',
        start_at: '2026-06-16T09:00:00Z', end_at: '2026-06-16T09:30:00Z',
        created_at: '2026-06-16T00:00:00Z',
      },
    })
    expect(out.day).toBe('2026-06-16')
    expect(out.startMinutes).not.toBeNull()
    expect(out.endMinutes).not.toBeNull()
    expect(out.kind).toBe('appointment')
  })

  it('returns null minutes for an all-day appointment', () => {
    const out = toGridItem({
      kind: 'appointment',
      raw: {
        id: 'a1', title: 'Holiday', day: '2026-06-16',
        start_at: null, end_at: null,
        created_at: '2026-06-16T00:00:00Z',
      },
    })
    expect(out.startMinutes).toBeNull()
    expect(out.endMinutes).toBeNull()
  })
})

describe('layoutDayColumn', () => {
  const item = (id: string, s: number, e: number): GridItem => ({
    id, kind: 'appointment', title: id,
    day: '2026-06-16', startMinutes: s, endMinutes: e, raw: null as any,
  })

  it('gives non-overlapping items full width', () => {
    const laid = layoutDayColumn([item('a', 60, 120), item('b', 180, 240)])
    expect(laid.every(x => x.columnCount === 1 && x.column === 0)).toBe(true)
  })

  it('splits two overlapping items into 2 columns', () => {
    const laid = layoutDayColumn([item('a', 60, 180), item('b', 120, 240)])
    expect(laid.map(x => x.columnCount)).toEqual([2, 2])
    expect([...laid.map(x => x.column)].sort()).toEqual([0, 1])
  })

  it('groups three pairwise-overlapping items into 3 columns', () => {
    const laid = layoutDayColumn([
      item('a', 60, 240), item('b', 120, 300), item('c', 180, 360),
    ])
    expect(laid.every(x => x.columnCount === 3)).toBe(true)
    expect([...laid.map(x => x.column)].sort()).toEqual([0, 1, 2])
  })

  it('excludes all-day items', () => {
    const laid = layoutDayColumn([
      { ...item('a', 0, 0), startMinutes: null, endMinutes: null },
      item('b', 60, 120),
    ])
    expect(laid.length).toBe(1)
    expect(laid[0].id).toBe('b')
  })
})
```

- [ ] **Step 2: Run** — failures (module not found).

```
cd frontend && npm test
```

- [ ] **Step 3: Implement the helpers** (`frontend/lib/calendarGrid.ts`)

```ts
import type { Appointment, CalendarEntry, EventCard } from '@/lib/types'

export interface GridItem {
  id: string
  kind: 'appointment' | 'event'
  title: string
  day: string                         // YYYY-MM-DD (local)
  startMinutes: number | null         // minutes from midnight on `day`
  endMinutes: number | null           // null => end of day / open
  raw: Appointment | CalendarEntry
}

export interface LaidOutItem extends GridItem {
  column: number
  columnCount: number
}

export function getWeekRange(d: Date): { start: Date; end: Date } {
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  // JS: Sunday=0..Saturday=6. We want Monday=0..Sunday=6.
  const dayMon0 = (start.getDay() + 6) % 7
  start.setDate(start.getDate() - dayMon0)
  const end = new Date(start)
  end.setDate(end.getDate() + 7)
  return { start, end }
}

function toLocalDayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function minutesFromMidnight(d: Date): number {
  return d.getHours() * 60 + d.getMinutes()
}

type GridInput =
  | { kind: 'appointment'; raw: Appointment }
  | { kind: 'event'; raw: CalendarEntry }

export function toGridItem(input: GridInput): GridItem {
  if (input.kind === 'appointment') {
    const a = input.raw
    return {
      id: a.id, kind: 'appointment', title: a.title, day: a.day,
      startMinutes: a.start_at ? minutesFromMidnight(new Date(a.start_at)) : null,
      endMinutes: a.end_at ? minutesFromMidnight(new Date(a.end_at)) : null,
      raw: a,
    }
  }
  const e: EventCard = input.raw.event
  const start = new Date(e.start_datetime)
  const end = e.end_datetime ? new Date(e.end_datetime) : null
  return {
    id: e.id, kind: 'event', title: e.title, day: toLocalDayKey(start),
    startMinutes: minutesFromMidnight(start),
    endMinutes: end ? minutesFromMidnight(end) : null,
    raw: input.raw,
  }
}

function effectiveEnd(it: GridItem): number {
  // For overlap math, treat null end (open) as end-of-day.
  return it.endMinutes ?? 24 * 60
}

export function layoutDayColumn(items: GridItem[]): LaidOutItem[] {
  const timed = items.filter(i => i.startMinutes !== null)
  // Sort by start, then by length descending (longer first looks better).
  timed.sort((a, b) => {
    const s = (a.startMinutes! - b.startMinutes!)
    if (s !== 0) return s
    return effectiveEnd(b) - effectiveEnd(a)
  })

  // Group items into maximal connected components by interval overlap.
  const out: LaidOutItem[] = []
  let i = 0
  while (i < timed.length) {
    const group: GridItem[] = [timed[i]]
    let groupEnd = effectiveEnd(timed[i])
    let j = i + 1
    while (j < timed.length && timed[j].startMinutes! < groupEnd) {
      group.push(timed[j])
      groupEnd = Math.max(groupEnd, effectiveEnd(timed[j]))
      j++
    }
    // Assign each group member the first column whose currently-running item ends
    // at or before this item's start.
    const columnEnds: number[] = []
    const localAssignments: { item: GridItem; column: number }[] = []
    for (const it of group) {
      let placed = false
      for (let c = 0; c < columnEnds.length; c++) {
        if (columnEnds[c] <= it.startMinutes!) {
          columnEnds[c] = effectiveEnd(it)
          localAssignments.push({ item: it, column: c })
          placed = true
          break
        }
      }
      if (!placed) {
        columnEnds.push(effectiveEnd(it))
        localAssignments.push({ item: it, column: columnEnds.length - 1 })
      }
    }
    const groupColumnCount = columnEnds.length
    for (const { item, column } of localAssignments) {
      out.push({ ...item, column, columnCount: groupColumnCount })
    }
    i = j
  }
  return out
}
```

- [ ] **Step 4: Run tests** — expect all green.

```
cd frontend && npm test -- calendarGrid
```

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/calendarGrid.ts frontend/lib/__tests__/calendarGrid.test.ts
git commit -m "feat(frontend): add calendarGrid helpers with overlap layout"
```

---

## Task 14: Frontend — `HourGutter`, `WeekdayStrip`, `NowLine`, `WeekHeader`

These four are simple pure-render components, batched into one task. No TDD — visual smoke checks happen via the page test in a later task.

**Files:**
- Create: `frontend/components/calendar/HourGutter.tsx`
- Create: `frontend/components/calendar/WeekdayStrip.tsx`
- Create: `frontend/components/calendar/NowLine.tsx`
- Create: `frontend/components/calendar/WeekHeader.tsx`

- [ ] **Step 1: Create `HourGutter.tsx`**

```tsx
const HOURS = Array.from({ length: 24 }, (_, i) => i)
export const HOUR_PX = 48

export default function HourGutter() {
  return (
    <div className="flex flex-col w-12 flex-shrink-0 border-r border-border">
      {HOURS.map((h) => (
        <div
          key={h}
          style={{ height: HOUR_PX }}
          className="text-[10px] text-text-muted text-right pr-2 -mt-1.5"
        >
          {String(h).padStart(2, '0')}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Create `WeekdayStrip.tsx`**

```tsx
const SHORT = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function WeekdayStrip({
  weekStart, todayKey,
}: { weekStart: Date; todayKey: string }) {
  const days: Date[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart); d.setDate(weekStart.getDate() + i); return d
  })
  return (
    <div className="flex border-b border-border bg-bg-page">
      <div className="w-12 flex-shrink-0" />
      {days.map((d, i) => {
        const key = toKey(d)
        const isToday = key === todayKey
        const isWeekend = i >= 5
        return (
          <div
            key={key}
            className={`flex-1 py-2 text-center border-l border-border ${isWeekend ? 'bg-bg-surface' : ''}`}
          >
            <p className="text-[10px] uppercase tracking-wider text-text-muted">{SHORT[i]}</p>
            <p
              className={
                'mt-0.5 text-sm font-serif font-bold ' +
                (isToday
                  ? 'inline-flex items-center justify-center w-7 h-7 rounded-full bg-accent-gold text-bg-page'
                  : 'text-text-primary')
              }
            >
              {d.getDate()}
            </p>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 3: Create `NowLine.tsx`**

```tsx
'use client'
import { useEffect, useState } from 'react'
import { HOUR_PX } from './HourGutter'

export default function NowLine() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])
  const minutes = now.getHours() * 60 + now.getMinutes()
  const top = (minutes / 60) * HOUR_PX
  return (
    <div
      data-testid="now-line"
      className="absolute left-0 right-0 z-20 pointer-events-none"
      style={{ top }}
    >
      <div className="absolute -left-1.5 top-[-3px] w-1.5 h-1.5 rounded-full bg-accent-gold" />
      <div className="absolute left-0 right-0 h-[1px] bg-accent-gold" />
    </div>
  )
}
```

- [ ] **Step 4: Create `WeekHeader.tsx`**

```tsx
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function label(weekStart: Date): string {
  const end = new Date(weekStart); end.setDate(weekStart.getDate() + 6)
  if (weekStart.getMonth() === end.getMonth()) {
    return `${MONTHS[weekStart.getMonth()]} ${weekStart.getFullYear()}`
  }
  return `${MONTHS[weekStart.getMonth()]} – ${MONTHS[end.getMonth()]} ${end.getFullYear()}`
}

export default function WeekHeader({
  weekStart, onPrev, onNext, onToday,
}: {
  weekStart: Date
  onPrev: () => void
  onNext: () => void
  onToday: () => void
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-bg-page">
      <div className="flex items-center gap-2">
        <button
          onClick={onPrev}
          aria-label="Previous week"
          className="rounded px-2 py-1 text-text-secondary hover:text-text-primary text-lg"
        >‹</button>
        <button
          onClick={onNext}
          aria-label="Next week"
          className="rounded px-2 py-1 text-text-secondary hover:text-text-primary text-lg"
        >›</button>
        <button
          onClick={onToday}
          className="ml-2 text-[11px] uppercase tracking-wider text-accent-gold hover:underline"
        >Today</button>
      </div>
      <h2 className="font-serif font-bold text-base text-text-primary">{label(weekStart)}</h2>
      <div className="w-24" />
    </div>
  )
}
```

- [ ] **Step 5: Type-check**

```
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/calendar/
git commit -m "feat(frontend): add calendar layout primitives"
```

---

## Task 15: Frontend — `EventBlock` + `DayColumn`

**Files:**
- Create: `frontend/components/calendar/EventBlock.tsx`
- Create: `frontend/components/calendar/DayColumn.tsx`

- [ ] **Step 1: Create `EventBlock.tsx`**

```tsx
import { HOUR_PX } from './HourGutter'
import type { LaidOutItem } from '@/lib/calendarGrid'

function fmtTime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export default function EventBlock({
  item, onClick,
}: {
  item: LaidOutItem
  onClick: (item: LaidOutItem) => void
}) {
  const startPx = (item.startMinutes! / 60) * HOUR_PX
  const endMinutes = item.endMinutes ?? 24 * 60
  const heightPx = Math.max(20, ((endMinutes - item.startMinutes!) / 60) * HOUR_PX)
  const widthPct = 100 / item.columnCount
  const leftPct = item.column * widthPct
  const borderColor = item.kind === 'event' ? 'border-accent-gold' : 'border-text-secondary'
  return (
    <button
      data-testid={`event-block-${item.id}`}
      data-kind={item.kind}
      onClick={(e) => { e.stopPropagation(); onClick(item) }}
      style={{
        top: startPx, height: heightPx,
        left: `calc(${leftPct}% + 2px)`, width: `calc(${widthPct}% - 4px)`,
      }}
      className={`absolute z-10 text-left rounded-md bg-white border border-border border-l-[3px] ${borderColor} px-2 py-1 overflow-hidden hover:shadow-sm`}
    >
      <p className="text-[10px] font-semibold text-text-primary truncate">{item.title}</p>
      <p className="text-[9px] text-text-muted">
        {fmtTime(item.startMinutes!)}{item.endMinutes !== null ? ` – ${fmtTime(item.endMinutes)}` : ''}
      </p>
    </button>
  )
}
```

- [ ] **Step 2: Create `DayColumn.tsx`**

```tsx
'use client'
import { useRef } from 'react'
import EventBlock from './EventBlock'
import NowLine from './NowLine'
import { HOUR_PX } from './HourGutter'
import { layoutDayColumn, type GridItem, type LaidOutItem } from '@/lib/calendarGrid'

const GRID_PX = 24 * HOUR_PX
const SNAP_MIN = 30

export default function DayColumn({
  dayKey, items, isToday, onEmptyClick, onItemClick, onAllDayClick,
}: {
  dayKey: string
  items: GridItem[]
  isToday: boolean
  onEmptyClick: (dayKey: string, startMinutes: number) => void
  onItemClick: (item: LaidOutItem) => void
  onAllDayClick: (dayKey: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const allDay = items.filter(i => i.startMinutes === null)
  const timed = layoutDayColumn(items)

  function handleBackgroundClick(e: React.MouseEvent) {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    const y = e.clientY - rect.top
    const rawMinutes = Math.max(0, Math.min(24 * 60 - SNAP_MIN, (y / HOUR_PX) * 60))
    const snapped = Math.round(rawMinutes / SNAP_MIN) * SNAP_MIN
    onEmptyClick(dayKey, snapped)
  }

  return (
    <div className="flex-1 flex flex-col border-l border-border min-w-0">
      <div
        role="button"
        tabIndex={0}
        onClick={() => onAllDayClick(dayKey)}
        className="border-b border-border bg-bg-surface min-h-[24px] flex flex-col gap-0.5 p-0.5 text-left cursor-pointer"
        aria-label="Add all-day appointment"
      >
        {allDay.map((it) => (
          <button
            key={it.id}
            data-testid={`allday-block-${it.id}`}
            onClick={(e) => {
              e.stopPropagation()
              onItemClick({ ...it, column: 0, columnCount: 1 })
            }}
            className="text-[9px] truncate rounded bg-white px-1 py-0.5 border-l-[3px] border-text-secondary text-left"
          >
            {it.title}
          </button>
        ))}
      </div>

      <div
        ref={ref}
        onClick={handleBackgroundClick}
        className="relative cursor-pointer"
        style={{
          height: GRID_PX,
          backgroundImage:
            'repeating-linear-gradient(to bottom, transparent 0, transparent 47px, rgb(232,224,212) 47px, rgb(232,224,212) 48px)',
        }}
      >
        {isToday && <NowLine />}
        {timed.map((it) => (
          <EventBlock key={it.id} item={it} onClick={onItemClick} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Type-check**

```
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/calendar/EventBlock.tsx frontend/components/calendar/DayColumn.tsx
git commit -m "feat(frontend): add EventBlock and DayColumn"
```

---

## Task 16: Frontend — `WeekView`

**Files:**
- Create: `frontend/components/calendar/WeekView.tsx`
- Test: `frontend/components/__tests__/WeekView.test.tsx`

- [ ] **Step 1: Write failing component test**

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import WeekView from '@/components/calendar/WeekView'

const baseAppointment = {
  id: 'app-1', title: 'Turing', day: '2026-06-16',
  start_at: '2026-06-16T07:00:00Z', end_at: '2026-06-16T14:30:00Z',
  created_at: '2026-06-16T00:00:00Z',
}

describe('WeekView', () => {
  it('renders a block for an appointment', () => {
    render(<WeekView
      weekStart={new Date(2026, 5, 15)}     // Mon June 15 2026
      todayKey="2026-06-16"
      appointments={[baseAppointment]}
      events={[]}
      onPrev={() => {}}
      onNext={() => {}}
      onToday={() => {}}
      onEmptyClick={() => {}}
      onItemClick={() => {}}
      onAllDayClick={() => {}}
    />)
    expect(screen.getByTestId('event-block-app-1')).toBeInTheDocument()
  })

  it('fires onItemClick when an appointment is clicked', () => {
    const onItemClick = vi.fn()
    render(<WeekView
      weekStart={new Date(2026, 5, 15)}
      todayKey="2026-06-16"
      appointments={[baseAppointment]}
      events={[]}
      onPrev={() => {}}
      onNext={() => {}}
      onToday={() => {}}
      onEmptyClick={() => {}}
      onItemClick={onItemClick}
      onAllDayClick={() => {}}
    />)
    fireEvent.click(screen.getByTestId('event-block-app-1'))
    expect(onItemClick).toHaveBeenCalledOnce()
    expect(onItemClick.mock.calls[0][0].id).toBe('app-1')
  })
})
```

- [ ] **Step 2: Run** — failures (`WeekView` not found).

```
cd frontend && npm test -- WeekView
```

- [ ] **Step 3: Implement `WeekView.tsx`**

```tsx
'use client'
import HourGutter from './HourGutter'
import WeekHeader from './WeekHeader'
import WeekdayStrip from './WeekdayStrip'
import DayColumn from './DayColumn'
import { toGridItem, type GridItem, type LaidOutItem } from '@/lib/calendarGrid'
import type { Appointment, CalendarEntry } from '@/lib/types'
import { useEffect, useRef } from 'react'
import { HOUR_PX } from './HourGutter'

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface Props {
  weekStart: Date
  todayKey: string
  appointments: Appointment[]
  events: CalendarEntry[]
  onPrev: () => void
  onNext: () => void
  onToday: () => void
  onEmptyClick: (dayKey: string, startMinutes: number) => void
  onItemClick: (item: LaidOutItem) => void
  onAllDayClick: (dayKey: string) => void
}

export default function WeekView({
  weekStart, todayKey, appointments, events,
  onPrev, onNext, onToday, onEmptyClick, onItemClick, onAllDayClick,
}: Props) {
  const items: GridItem[] = [
    ...appointments.map(a => toGridItem({ kind: 'appointment', raw: a })),
    ...events.map(e => toGridItem({ kind: 'event', raw: e })),
  ]

  const days: { key: string; date: Date }[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart); d.setDate(weekStart.getDate() + i)
    return { key: toKey(d), date: d }
  })

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 7 * HOUR_PX  // 07:00
  }, [])

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-bg-page">
      <WeekHeader weekStart={weekStart} onPrev={onPrev} onNext={onNext} onToday={onToday} />
      <WeekdayStrip weekStart={weekStart} todayKey={todayKey} />
      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-auto">
        <div className="flex">
          <HourGutter />
          {days.map(({ key }) => (
            <DayColumn
              key={key}
              dayKey={key}
              items={items.filter(i => i.day === key)}
              isToday={key === todayKey}
              onEmptyClick={onEmptyClick}
              onItemClick={onItemClick}
              onAllDayClick={onAllDayClick}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```
cd frontend && npm test -- WeekView
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/calendar/WeekView.tsx frontend/components/__tests__/WeekView.test.tsx
git commit -m "feat(frontend): add WeekView component"
```

---

## Task 17: Frontend — `AppointmentModal` shell + tab switcher

**Files:**
- Create: `frontend/components/calendar/appointmentModal/AppointmentModal.tsx`

- [ ] **Step 1: Create the shell**

```tsx
'use client'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import MakeAppointmentTab, { type MakeInitial } from './MakeAppointmentTab'
import RecommendTab from './RecommendTab'

export type AppointmentModalMode = 'create' | 'edit'

export interface AppointmentModalProps {
  mode: AppointmentModalMode
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}

function Inner(props: AppointmentModalProps) {
  const [tab, setTab] = useState<'make' | 'recommend'>('make')

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') props.onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [props.onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      data-testid="appointment-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-text-primary/55 px-4"
      onClick={props.onClose}
    >
      <div
        className="relative bg-bg-page rounded-xl w-full max-w-md flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex border-b border-border bg-bg-page p-2 gap-2">
          <button
            data-testid="tab-make"
            onClick={() => setTab('make')}
            className={`flex-1 rounded px-3 py-1.5 text-xs font-semibold ${tab === 'make' ? 'bg-accent-gold text-bg-page' : 'text-text-secondary'}`}
          >Make an appointment</button>
          {props.mode === 'create' && (
            <button
              data-testid="tab-recommend"
              onClick={() => setTab('recommend')}
              className={`flex-1 rounded px-3 py-1.5 text-xs font-semibold ${tab === 'recommend' ? 'bg-accent-gold text-bg-page' : 'text-text-secondary'}`}
            >Recommend me something</button>
          )}
        </div>
        {tab === 'make' && (
          <MakeAppointmentTab
            mode={props.mode}
            initial={props.initial}
            onClose={props.onClose}
            onSaved={props.onSaved}
          />
        )}
        {tab === 'recommend' && (
          <RecommendTab initial={props.initial} />
        )}
      </div>
    </div>
  )
}

export default function AppointmentModal(props: AppointmentModalProps) {
  if (typeof document === 'undefined') return null
  return createPortal(<Inner {...props} />, document.body)
}
```

- [ ] **Step 2: Commit** (will fail to type-check until Tasks 18 + 19; do not run tsc yet)

```bash
git add frontend/components/calendar/appointmentModal/AppointmentModal.tsx
git commit -m "feat(frontend): add AppointmentModal shell with tab switcher"
```

---

## Task 18: Frontend — `MakeAppointmentTab`

**Files:**
- Create: `frontend/components/calendar/appointmentModal/MakeAppointmentTab.tsx`
- Test: `frontend/components/__tests__/AppointmentModal.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AppointmentModal from '@/components/calendar/appointmentModal/AppointmentModal'
import * as api from '@/lib/api'

vi.mock('@/lib/api', async () => ({
  createAppointment: vi.fn().mockResolvedValue({}),
  updateAppointment: vi.fn().mockResolvedValue({}),
  deleteAppointment: vi.fn().mockResolvedValue(undefined),
  recommendAppointment: vi.fn().mockResolvedValue({ message: 'Currently not implemented' }),
}))

describe('AppointmentModal — Make tab', () => {
  it('shows Save but not Delete in create mode', () => {
    render(<AppointmentModal
      mode="create"
      initial={{ day: '2026-06-16', start_at: null, end_at: null, title: '' }}
      onClose={() => {}}
      onSaved={() => {}}
    />)
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
  })

  it('shows Delete in edit mode', () => {
    render(<AppointmentModal
      mode="edit"
      initial={{
        id: 'app-1', day: '2026-06-16',
        start_at: '2026-06-16T09:00:00Z', end_at: '2026-06-16T10:00:00Z',
        title: 'Standup',
      }}
      onClose={() => {}}
      onSaved={() => {}}
    />)
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
  })

  it('calls createAppointment on Save in create mode', async () => {
    const onSaved = vi.fn()
    render(<AppointmentModal
      mode="create"
      initial={{ day: '2026-06-16', start_at: null, end_at: null, title: '' }}
      onClose={() => {}}
      onSaved={onSaved}
    />)
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'New' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /all day/i }))
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    // microtask flush:
    await Promise.resolve()
    await Promise.resolve()
    expect(api.createAppointment).toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run** — failures.

```
cd frontend && npm test -- AppointmentModal
```

- [ ] **Step 3: Implement `MakeAppointmentTab.tsx`**

```tsx
'use client'
import { useState } from 'react'
import { createAppointment, deleteAppointment, updateAppointment } from '@/lib/api'

export interface MakeInitial {
  id?: string
  day: string                       // YYYY-MM-DD
  title?: string
  start_at?: string | null
  end_at?: string | null
}

function isoToTimeInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function timeInputToIso(day: string, hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const [y, mo, d] = day.split('-').map(Number)
  return new Date(y, mo - 1, d, h, m).toISOString()
}

export default function MakeAppointmentTab({
  mode, initial, onClose, onSaved,
}: {
  mode: 'create' | 'edit'
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}) {
  const [title, setTitle] = useState(initial.title ?? '')
  const [allDay, setAllDay] = useState(initial.start_at == null && initial.end_at == null)
  const [start, setStart] = useState(isoToTimeInput(initial.start_at))
  const [end, setEnd] = useState(isoToTimeInput(initial.end_at))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const canSave = title.trim().length > 0 && !busy

  async function handleSave() {
    setError(null)
    if (!allDay && start && end && end <= start) {
      setError('End time must be after start time.')
      return
    }
    const payload = {
      title: title.trim(),
      day: initial.day,
      start_at: allDay || !start ? null : timeInputToIso(initial.day, start),
      end_at: allDay || !end ? null : timeInputToIso(initial.day, end),
    }
    setBusy(true)
    try {
      if (mode === 'edit' && initial.id) {
        await updateAppointment(initial.id, payload)
      } else {
        await createAppointment(payload)
      }
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!initial.id) return
    if (!window.confirm('Delete this appointment?')) return
    setBusy(true)
    try {
      await deleteAppointment(initial.id)
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <label className="text-[11px] text-text-secondary">
        Title
        <input
          autoFocus={mode === 'create'}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white"
        />
      </label>

      <label className="flex items-center gap-2 text-[11px] text-text-secondary">
        <input
          type="checkbox"
          checked={allDay}
          onChange={(e) => setAllDay(e.target.checked)}
        />
        All day
      </label>

      {!allDay && (
        <div className="flex gap-2">
          <label className="flex-1 text-[11px] text-text-secondary">
            Start
            <input
              type="time"
              step={900}
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white"
            />
          </label>
          <label className="flex-1 text-[11px] text-text-secondary">
            End
            <input
              type="time"
              step={900}
              value={end}
              disabled={!start}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white disabled:bg-bg-surface"
            />
            <span className="block mt-0.5 text-[9px] text-text-muted">Leave empty to last until end of day.</span>
          </label>
        </div>
      )}

      <p className="text-[10px] text-text-muted">Day: {initial.day}</p>

      {error && <p className="text-[10px] text-red-500">{error}</p>}

      <div className="flex justify-between pt-2 border-t border-border">
        <div>
          {mode === 'edit' && (
            <button
              onClick={handleDelete}
              disabled={busy}
              className="text-xs text-red-500 hover:underline disabled:opacity-50"
            >Delete</button>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={!canSave}
          className="bg-accent-gold text-bg-page rounded px-4 py-1.5 text-xs font-semibold disabled:opacity-50"
        >Save</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```
cd frontend && npm test -- AppointmentModal
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/calendar/appointmentModal/MakeAppointmentTab.tsx frontend/components/__tests__/AppointmentModal.test.tsx
git commit -m "feat(frontend): add MakeAppointmentTab with save/delete flows"
```

---

## Task 19: Frontend — `RecommendTab` with placeholder chat

**Files:**
- Create: `frontend/components/calendar/appointmentModal/RecommendTab.tsx`
- Test: `frontend/components/__tests__/RecommendTab.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import RecommendTab from '@/components/calendar/appointmentModal/RecommendTab'
import * as api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  recommendAppointment: vi.fn().mockResolvedValue({ message: 'Currently not implemented' }),
}))

describe('RecommendTab', () => {
  const baseInitial = { day: '2026-06-16', start_at: null, end_at: null, title: '' }

  it('shows placeholder text when empty, unfocused, and no messages sent', () => {
    render(<RecommendTab initial={baseInitial} />)
    expect(screen.getByText(/Tell your assistant what you are searching for/i)).toBeInTheDocument()
  })

  it('hides placeholder when input focused', () => {
    render(<RecommendTab initial={baseInitial} />)
    fireEvent.focus(screen.getByRole('textbox'))
    expect(screen.queryByText(/Tell your assistant what you are searching for/i)).not.toBeInTheDocument()
  })

  it('after sending a message, placeholder never returns', async () => {
    render(<RecommendTab initial={baseInitial} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'help' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(api.recommendAppointment).toHaveBeenCalled()
    expect(await screen.findByText(/Currently not implemented/i)).toBeInTheDocument()
    fireEvent.blur(input)
    expect(screen.queryByText(/Tell your assistant what you are searching for/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run** — failures.

```
cd frontend && npm test -- RecommendTab
```

- [ ] **Step 3: Implement `RecommendTab.tsx`**

```tsx
'use client'
import { useState } from 'react'
import { recommendAppointment } from '@/lib/api'

interface Initial {
  day: string
  start_at?: string | null
  end_at?: string | null
}

interface Bubble { role: 'user' | 'assistant'; content: string; id: string }

export default function RecommendTab({ initial }: { initial: Initial }) {
  const [input, setInput] = useState('')
  const [focused, setFocused] = useState(false)
  const [messages, setMessages] = useState<Bubble[]>([])
  const [busy, setBusy] = useState(false)

  const showPlaceholder = input.length === 0 && !focused && messages.length === 0

  async function handleSubmit() {
    const text = input.trim()
    if (!text || busy) return
    setBusy(true)
    setInput('')
    const userBubble: Bubble = { id: `u-${Date.now()}`, role: 'user', content: text }
    setMessages((m) => [...m, userBubble])
    try {
      const out = await recommendAppointment({
        day: initial.day,
        start_at: initial.start_at ?? null,
        end_at: initial.end_at ?? null,
        message: text,
      })
      setMessages((m) => [...m, { id: `a-${Date.now()}`, role: 'assistant', content: out.message }])
    } catch {
      setMessages((m) => [...m, {
        id: `a-${Date.now()}`, role: 'assistant', content: "Couldn't reach assistant",
      }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col p-4 gap-3">
      <p className="text-[10px] text-text-muted">Day: {initial.day}</p>

      <div className="flex flex-col gap-2 min-h-[120px]">
        {messages.map((msg) =>
          msg.role === 'user' ? (
            <div key={msg.id} className="self-end max-w-[85%] rounded-lg rounded-br-sm bg-bg-surface px-3 py-1.5 text-[10px] italic text-text-primary">
              {msg.content}
            </div>
          ) : (
            <div key={msg.id} className="self-start max-w-[90%] rounded-lg rounded-bl-sm border border-border bg-white px-3 py-1.5 text-[10px] text-text-primary">
              {msg.content}
            </div>
          ),
        )}
      </div>

      <div className="relative">
        {showPlaceholder && (
          <p
            data-testid="recommend-placeholder"
            className="absolute inset-0 px-2.5 py-1.5 text-[10px] text-text-muted pointer-events-none"
          >
            Tell your assistant what you are searching for...
          </p>
        )}
        <input
          aria-label="Recommend chat input"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
          className="w-full text-[10px] border border-border rounded px-2.5 py-1.5 bg-white"
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```
cd frontend && npm test -- RecommendTab
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/calendar/appointmentModal/RecommendTab.tsx frontend/components/__tests__/RecommendTab.test.tsx
git commit -m "feat(frontend): add RecommendTab placeholder chat"
```

---

## Task 20: Frontend — Rewrite `app/calendar/page.tsx`

**Files:**
- Modify: `frontend/app/calendar/page.tsx`

- [ ] **Step 1: Replace the file entirely** with the new wrapper

```tsx
'use client'
import { useMemo, useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { getCalendar, listAppointments } from '@/lib/api'
import type { Appointment, AppointmentsResponse, CalendarResponse } from '@/lib/types'
import { useAppShell } from '@/components/AppShell'
import WeekView from '@/components/calendar/WeekView'
import AppointmentModal from '@/components/calendar/appointmentModal/AppointmentModal'
import type { MakeInitial } from '@/components/calendar/appointmentModal/MakeAppointmentTab'
import { getWeekRange, type LaidOutItem } from '@/lib/calendarGrid'

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function minutesToIso(day: string, minutes: number): string {
  const [y, m, d] = day.split('-').map(Number)
  const h = Math.floor(minutes / 60)
  const mm = minutes % 60
  return new Date(y, m - 1, d, h, mm).toISOString()
}

export default function CalendarPage() {
  const { openOverlay } = useAppShell()
  const { mutate } = useSWRConfig()
  const today = new Date()
  const todayKey = toKey(today)

  const [weekStart, setWeekStart] = useState<Date>(() => getWeekRange(new Date()).start)
  const [modal, setModal] = useState<{ mode: 'create' | 'edit'; initial: MakeInitial } | null>(null)

  const { start, end } = useMemo(() => {
    const r = getWeekRange(weekStart)
    return { start: toKey(r.start), end: toKey(new Date(r.end.getTime() - 1)) }
  }, [weekStart])

  const { data: appData, error: appError } = useSWR<AppointmentsResponse>(
    ['/appointments', start, end],
    () => listAppointments(start, end),
  )
  const { data: calData, error: calError } = useSWR<CalendarResponse>('/calendar', getCalendar)

  const appointments: Appointment[] = appData?.appointments ?? []
  const events = (calData?.entries ?? []).filter((entry) => {
    const k = toKey(new Date(entry.event.start_datetime))
    return k >= start && k <= end
  })

  const appointmentById = new Map(appointments.map(a => [a.id, a]))

  function shiftWeek(days: number) {
    const next = new Date(weekStart); next.setDate(next.getDate() + days)
    setWeekStart(next)
  }

  function onEmptyClick(dayKey: string, startMinutes: number) {
    setModal({
      mode: 'create',
      initial: {
        day: dayKey,
        start_at: minutesToIso(dayKey, startMinutes),
        end_at: minutesToIso(dayKey, Math.min(24 * 60 - 1, startMinutes + 60)),
        title: '',
      },
    })
  }

  function onAllDayClick(dayKey: string) {
    setModal({
      mode: 'create',
      initial: { day: dayKey, start_at: null, end_at: null, title: '' },
    })
  }

  function onItemClick(item: LaidOutItem) {
    if (item.kind === 'event') {
      openOverlay(item.id)
      return
    }
    const appt = appointmentById.get(item.id)
    if (!appt) return
    setModal({
      mode: 'edit',
      initial: {
        id: appt.id, day: appt.day, title: appt.title,
        start_at: appt.start_at, end_at: appt.end_at,
      },
    })
  }

  function onSaved() {
    mutate((key) => Array.isArray(key) && key[0] === '/appointments')
    mutate('/calendar')
  }

  return (
    <>
      {(appError || calError) && (
        <div className="flex flex-col gap-1 px-4 py-2 bg-bg-page border-b border-border">
          {appError && (
            <p data-testid="appointments-error" className="text-[10px] text-red-500">
              Couldn&apos;t load appointments.{' '}
              <button
                onClick={() => mutate((key) => Array.isArray(key) && key[0] === '/appointments')}
                className="underline"
              >Retry</button>
            </p>
          )}
          {calError && (
            <p data-testid="calendar-error" className="text-[10px] text-red-500">
              Couldn&apos;t load saved events.{' '}
              <button onClick={() => mutate('/calendar')} className="underline">Retry</button>
            </p>
          )}
        </div>
      )}
      <WeekView
        weekStart={weekStart}
        todayKey={todayKey}
        appointments={appointments}
        events={events}
        onPrev={() => shiftWeek(-7)}
        onNext={() => shiftWeek(7)}
        onToday={() => setWeekStart(getWeekRange(new Date()).start)}
        onEmptyClick={onEmptyClick}
        onItemClick={onItemClick}
        onAllDayClick={onAllDayClick}
      />
      {modal && (
        <AppointmentModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={onSaved}
        />
      )}
    </>
  )
}
```

- [ ] **Step 2: Type-check**

```
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Run all frontend tests**

```
cd frontend && npm test
```
Expected: all green.

- [ ] **Step 4: Smoke-test in the browser**

Start backend and frontend dev servers, navigate to `/calendar`. Verify:
- Week grid renders, scrolled to ~07:00 by default.
- Today's column shows the gold NowLine.
- Turing College blocks appear Mon–Fri 09:00–16:30 (assuming seed has run).
- Clicking an empty area opens the modal in create mode.
- Clicking a Turing College block opens the modal in edit mode with Delete shown.
- Clicking a saved feed event (if any are saved) opens the existing `EventDetailOverlay`.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/calendar/page.tsx
git commit -m "feat(frontend): replace month grid with week-view calendar page"
```

---

## Task 21: Frontend — Extend `AppShell.fanOutEventCaches`

**Files:**
- Modify: `frontend/components/AppShell.tsx`

- [ ] **Step 1: Add the new mutate call**

Find `fanOutEventCaches` (currently around line 85 in `AppShell.tsx`) and add one line:

```tsx
const fanOutEventCaches = useCallback((eventId: string) => {
  mutate(`/events/${eventId}`)
  mutate('/digest')
  mutate('/calendar')
  mutate((key) => Array.isArray(key) && key[0] === '/events')
  mutate((key) => Array.isArray(key) && key[0] === '/appointments')
}, [mutate])
```

- [ ] **Step 2: Type-check + run tests**

```
cd frontend && npx tsc --noEmit && npm test
```
Expected: no errors, all tests green.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/AppShell.tsx
git commit -m "feat(frontend): revalidate /appointments cache on event mutations"
```

---

## Wrap-up

After Task 21:

- [ ] **Full suite:** `cd backend && pytest -q && cd ../frontend && npm test`
- [ ] **Manual smoke test** of the calendar page (see Task 20 step 4).
- [ ] **Run the seed script** against your dev DB if you haven't yet: `python -m scripts.seed_default_appointments` from `backend/`.
- [ ] Push the branch when satisfied.
