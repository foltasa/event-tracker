# Timetable Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-store every event the AI assistant mentions (`[event:ID]`) as a Recommendation in the timetable; render it differently from saved events; allow the user to slot-in (accept) or slot-out (dismiss) per event; expose a settings toggle to disable the feature.

**Architecture:** Extend `SavedEvent` with a `kind` discriminant (`'saved' | 'recommendation'`) so a single table backs both. The conversational chat route scrapes `[event:ID]` refs from the assistant's final reply and inserts recommendation rows under existing uniqueness rules (skips events already saved). The frontend reads `kind` on `CalendarEntry` and `calendar_kind` on `EventWithContext`, branching `EventBlock` styling and the `EventDetailOverlay` action area accordingly. Settings flag lives inside the existing `users.settings` JSON dict (no migration for it).

**Tech Stack:** SQLAlchemy + Alembic (SQLite), FastAPI, LangGraph (already-built agent — only the chat route changes), Next.js 14 + SWR + Tailwind.

**Reference spec:** `docs/specs/2026-06-21-timetable-recommendations-design.md`

---

## File map

**Backend — created**
- `backend/app/db/migrations/versions/0005_saved_event_kind.py` — adds `kind` column.

**Backend — modified**
- `backend/app/db/models/saved_event.py` — `kind` mapped column.
- `backend/app/schemas/calendar.py` — `CalendarEntry.kind`.
- `backend/app/api/routes_calendar.py` — `kind` in response; new `POST /calendar/{event_id}/slot-in`.
- `backend/app/schemas/common.py` — `EventWithContext.calendar_kind`; `UserSettings.auto_recommendations_enabled`.
- `backend/app/api/routes_events.py` — populate `calendar_kind` in `_hydrate`.
- `backend/app/schemas/profile.py` — `SettingsUpdate.auto_recommendations_enabled`.
- `backend/app/api/routes_profile.py` — new `PUT /profile/settings` endpoint.
- `backend/app/api/routes_chat.py` — call `_persist_recommendations` after final answer.

**Backend — tests modified/created**
- `backend/tests/db/test_saved_event.py` — `kind` defaults / explicit recommendation.
- `backend/tests/api/test_routes_calendar.py` — `kind` field, `slot-in` endpoint.
- `backend/tests/api/test_routes_events.py` — `calendar_kind` in response.
- `backend/tests/api/test_routes_profile.py` — settings endpoint.
- `backend/tests/api/test_routes_chat.py` — recommendation persistence.

**Frontend — created**
- `frontend/app/settings/page.tsx` — settings page.
- `frontend/components/__tests__/SettingsPage.test.tsx` — tests.

**Frontend — modified**
- `frontend/lib/types.ts` — `CalendarEntry.kind`, `EventWithContext.calendar_kind`, `UserSettings.auto_recommendations_enabled`.
- `frontend/lib/api.ts` — `slotInRecommendation`, `updateProfileSettings`.
- `frontend/lib/calendarGrid.ts` — extended `kind` discriminant on `GridItem`.
- `frontend/components/calendar/EventBlock.tsx` — recommendation styling.
- `frontend/components/EventDetailOverlay.tsx` — three-state action area.
- `frontend/components/AppShell.tsx` — `handleSlotIn`, `calendar_kind` override map; slot-out clears both.
- `frontend/components/TopNav.tsx` — `'settings'` link.
- `frontend/lib/__tests__/calendarGrid.test.ts` — recommendation conversion.
- `frontend/components/__tests__/EventDetailOverlay.test.tsx` — branch tests.
- `frontend/components/__tests__/WeekView.test.tsx` (or new EventBlock test) — recommendation block visual.

---

## Conventions for this plan

- Commit after each task. Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`).
- Backend tests: `pytest path/test.py::test_name -v` from `backend/`.
- Frontend tests: `npm test -- <pattern>` from `frontend/`.
- Before staging files: prefer naming exact files instead of `git add -A`.
- Use parallel Bash calls when running multiple independent `git` commands (per project CLAUDE.md).

---

### Task 1: Add `kind` column to `saved_events`

**Files:**
- Modify: `backend/app/db/models/saved_event.py`
- Create: `backend/app/db/migrations/versions/0005_saved_event_kind.py`
- Modify: `backend/tests/db/test_saved_event.py`

- [ ] **Step 1: Write the failing test** in `backend/tests/db/test_saved_event.py` — append after the existing tests:

```python
def test_saved_event_kind_defaults_to_saved(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert s.kind == "saved"


def test_saved_event_kind_can_be_recommendation(db_session):
    _seed(db_session)
    s = SavedEvent(id="sav_1", user_id="local", event_id="evt_1", kind="recommendation")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert s.kind == "recommendation"
```

- [ ] **Step 2: Run to confirm fail**

From `backend/`:
```bash
pytest tests/db/test_saved_event.py::test_saved_event_kind_defaults_to_saved -v
```
Expected: FAIL (`AttributeError: kind` or DB column missing).

- [ ] **Step 3: Add the column to the model.** Replace the contents of `backend/app/db/models/saved_event.py` with:

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SavedEvent(Base):
    __tablename__ = "saved_events"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_saved_user_event"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="saved")
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
```

- [ ] **Step 4: Create migration 0005.** Write `backend/app/db/migrations/versions/0005_saved_event_kind.py`:

```python
"""saved_events.kind column

Revision ID: 0005_saved_event_kind
Revises: 0004_appointments
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_saved_event_kind"
down_revision: Union[str, Sequence[str], None] = "0004_appointments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "saved_events",
        sa.Column("kind", sa.String(), nullable=False, server_default="saved"),
    )


def downgrade() -> None:
    op.drop_column("saved_events", "kind")
```

- [ ] **Step 5: Run the tests again**

```bash
pytest tests/db/test_saved_event.py -v
```
Expected: all pass (including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/saved_event.py backend/app/db/migrations/versions/0005_saved_event_kind.py backend/tests/db/test_saved_event.py
git commit -m "feat(db): add kind column to saved_events (saved|recommendation)"
```

---

### Task 2: Surface `kind` on `GET /calendar`

**Files:**
- Modify: `backend/app/schemas/calendar.py`
- Modify: `backend/app/api/routes_calendar.py`
- Modify: `backend/tests/api/test_routes_calendar.py`

- [ ] **Step 1: Write failing test.** Append to `backend/tests/api/test_routes_calendar.py`:

```python
def test_get_calendar_includes_kind_saved_by_default(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})
    body = client.get("/calendar").json()
    assert body["entries"][0]["kind"] == "saved"


def test_get_calendar_returns_recommendation_kind(client, setup, db_session):
    import uuid
    from app.db.models import SavedEvent
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="local",
                              event_id="e1", kind="recommendation"))
    db_session.commit()
    body = client.get("/calendar").json()
    assert body["entries"][0]["kind"] == "recommendation"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/api/test_routes_calendar.py::test_get_calendar_includes_kind_saved_by_default -v
```
Expected: FAIL (`KeyError: 'kind'`).

- [ ] **Step 3: Extend the schema.** Edit `backend/app/schemas/calendar.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import EventCard, _JsonBase


class CalendarEntry(_JsonBase):
    id: str
    event: EventCard
    saved_at: datetime
    kind: Literal["saved", "recommendation"] = "saved"


class CalendarResponse(_JsonBase):
    entries: list[CalendarEntry] = Field(default_factory=list)
```

- [ ] **Step 4: Wire `kind` through the route.** In `backend/app/api/routes_calendar.py`, find the `get_calendar` function and update the comprehension to pass `kind`:

Replace the existing `entries = [...]` block with:

```python
    entries = [
        CalendarEntry(id=s.id, event=_event_to_card(e), saved_at=s.saved_at, kind=s.kind)
        for s, e in rows
    ]
```

Also update the `save_to_calendar` (POST) return — it constructs a `CalendarEntry`; pass `kind=existing.kind`:

```python
    return CalendarEntry(
        id=existing.id, event=_event_to_card(e),
        saved_at=existing.saved_at, kind=existing.kind,
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/api/test_routes_calendar.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/calendar.py backend/app/api/routes_calendar.py backend/tests/api/test_routes_calendar.py
git commit -m "feat(api): expose saved_event.kind on /calendar responses"
```

---

### Task 3: `POST /calendar/{event_id}/slot-in`

**Files:**
- Modify: `backend/app/api/routes_calendar.py`
- Modify: `backend/tests/api/test_routes_calendar.py`

- [ ] **Step 1: Write failing tests.** Append:

```python
def test_slot_in_promotes_recommendation_to_saved(client, setup, db_session):
    import uuid
    from app.db.models import SavedEvent
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="local",
                              event_id="e1", kind="recommendation"))
    db_session.commit()
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 200
    assert r.json()["kind"] == "saved"
    fresh = db_session.query(SavedEvent).filter_by(event_id="e1").one()
    assert fresh.kind == "saved"


def test_slot_in_idempotent_on_already_saved(client, setup, db_session):
    client.post("/calendar", json={"event_id": "e1"})  # creates kind='saved'
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 200
    assert r.json()["kind"] == "saved"


def test_slot_in_404_when_no_row(client, setup):
    r = client.post("/calendar/e1/slot-in")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/api/test_routes_calendar.py::test_slot_in_404_when_no_row -v
```
Expected: FAIL (route not found).

- [ ] **Step 3: Implement.** Add to `backend/app/api/routes_calendar.py` (after the DELETE handler):

```python
@router.post("/{event_id}/slot-in", response_model=CalendarEntry)
def slot_in(event_id: str, db: DbSession) -> CalendarEntry:
    user_id = get_current_user_id()
    row = (
        db.query(SavedEvent)
        .filter_by(user_id=user_id, event_id=event_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    e = db.query(Event).filter_by(id=event_id).one()
    if row.kind != "saved":
        row.kind = "saved"
        db.commit()
        db.refresh(row)
    return CalendarEntry(
        id=row.id, event=_event_to_card(e),
        saved_at=row.saved_at, kind=row.kind,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/api/test_routes_calendar.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_calendar.py backend/tests/api/test_routes_calendar.py
git commit -m "feat(api): POST /calendar/{event_id}/slot-in to accept a recommendation"
```

---

### Task 4: Add `calendar_kind` to `GET /events/{id}`

**Files:**
- Modify: `backend/app/schemas/common.py`
- Modify: `backend/app/api/routes_events.py`
- Modify: `backend/tests/api/test_routes_events.py`

- [ ] **Step 1: Write failing tests.** Open `backend/tests/api/test_routes_events.py`. Append (use the existing patterns there for setup):

```python
def test_event_detail_calendar_kind_null_when_not_in_calendar(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.commit()
    r = client.get("/events/evt")
    assert r.status_code == 200
    assert r.json()["calendar_kind"] is None


def test_event_detail_calendar_kind_saved(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, SavedEvent, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="evt"))
    db_session.commit()
    body = client.get("/events/evt").json()
    assert body["calendar_kind"] == "saved"
    assert body["is_saved"] is True


def test_event_detail_calendar_kind_recommendation(client, db_session):
    from datetime import datetime, timezone
    from app.db.models import Event, SavedEvent, User
    db_session.add(User(id="local", interest_tags=[]))
    db_session.add(Event(id="evt", external_id="x", source="eventbrite",
                         title="t", category="music", source_url="http://x",
                         start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc)))
    db_session.add(SavedEvent(id="s1", user_id="local", event_id="evt", kind="recommendation"))
    db_session.commit()
    body = client.get("/events/evt").json()
    assert body["calendar_kind"] == "recommendation"
    assert body["is_saved"] is True  # both kinds count as "in the calendar"
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/api/test_routes_events.py::test_event_detail_calendar_kind_null_when_not_in_calendar -v
```
Expected: FAIL.

- [ ] **Step 3: Schema.** In `backend/app/schemas/common.py` update `EventWithContext`:

```python
class EventWithContext(EventCard):
    user_sentiment: Sentiment | None = None
    user_comment: str | None = None
    is_saved: bool = False
    calendar_kind: Literal["saved", "recommendation"] | None = None
```

- [ ] **Step 4: Route.** Edit `backend/app/api/routes_events.py`:

Update `_hydrate` signature and body:

```python
def _hydrate(e: Event, sentiment, comment, calendar_kind) -> EventWithContext:
    return EventWithContext(
        id=e.id, title=e.title, summary=e.summary,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
        user_sentiment=sentiment,
        user_comment=comment,
        is_saved=calendar_kind is not None,
        calendar_kind=calendar_kind,
    )
```

In `list_events`, replace the `saved_set` query + hydrate call:

```python
    saved_map = {
        s.event_id: s.kind
        for s in db.query(SavedEvent).filter(
            SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids)
        ).all()
    }

    events = [
        _hydrate(
            r,
            fb_map.get(r.id).sentiment if fb_map.get(r.id) else None,
            fb_map.get(r.id).comment if fb_map.get(r.id) else None,
            saved_map.get(r.id),
        )
        for r in rows
    ]
```

In `get_event`, replace the `is_saved` computation and `_hydrate` call:

```python
    saved_row = (
        db.query(SavedEvent)
        .filter(SavedEvent.user_id == user_id, SavedEvent.event_id == event_id)
        .first()
    )
    return _hydrate(
        e,
        fb.sentiment if fb else None,
        fb.comment if fb else None,
        saved_row.kind if saved_row else None,
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/api/test_routes_events.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/common.py backend/app/api/routes_events.py backend/tests/api/test_routes_events.py
git commit -m "feat(api): expose calendar_kind on event responses"
```

---

### Task 5: Settings flag — schema + `PUT /profile/settings`

**Files:**
- Modify: `backend/app/schemas/common.py`
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Modify: `backend/tests/api/test_routes_profile.py`

- [ ] **Step 1: Write failing tests.** Append to `backend/tests/api/test_routes_profile.py`:

```python
def test_get_profile_settings_default_auto_recommendations_true(client, user):
    body = client.get("/profile").json()
    assert body["settings"]["auto_recommendations_enabled"] is True


def test_put_profile_settings_persists_flag(client, user, db_session):
    r = client.put("/profile/settings", json={"auto_recommendations_enabled": False})
    assert r.status_code == 200
    assert r.json()["settings"]["auto_recommendations_enabled"] is False
    # Verify reload sees the flag too.
    body = client.get("/profile").json()
    assert body["settings"]["auto_recommendations_enabled"] is False


def test_put_profile_settings_partial_update_keeps_other_keys(client, user, db_session):
    client.put("/profile/settings", json={"auto_recommendations_enabled": False})
    # Now toggle it back via a separate request — confirms merge semantics.
    r = client.put("/profile/settings", json={"auto_recommendations_enabled": True})
    assert r.json()["settings"]["auto_recommendations_enabled"] is True
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/api/test_routes_profile.py::test_get_profile_settings_default_auto_recommendations_true -v
```
Expected: FAIL.

- [ ] **Step 3: Add the field to the Pydantic settings models.**

In `backend/app/schemas/common.py`, update `UserSettings`:

```python
class UserSettings(_JsonBase):
    tool_toggles: dict[str, bool] = Field(default_factory=dict)
    llm_provider: LLMProvider = "openai"
    llm_model: str | None = None
    auto_recommendations_enabled: bool = True
```

In `backend/app/schemas/profile.py`, update `SettingsUpdate`:

```python
class SettingsUpdate(_JsonBase):
    tool_toggles: dict[str, bool] | None = None
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None
    auto_recommendations_enabled: bool | None = None
```

- [ ] **Step 4: Add the endpoint.** In `backend/app/api/routes_profile.py`, add the import and route:

```python
from app.schemas.profile import (
    OnboardingRequest,
    SettingsUpdate,
    UserProfileResponse,
    UserProfileUpdate,
)
```

Append:

```python
@router.put("/settings", response_model=UserProfileResponse)
def update_settings(payload: SettingsUpdate, db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    current = dict(u.settings or {})
    update = payload.model_dump(exclude_unset=True)
    current.update(update)
    u.settings = current
    db.commit()
    db.refresh(u)
    return _to_response(u)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/api/test_routes_profile.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/common.py backend/app/schemas/profile.py backend/app/api/routes_profile.py backend/tests/api/test_routes_profile.py
git commit -m "feat(api): add auto_recommendations_enabled to user settings"
```

---

### Task 6: Chat hook — persist recommendations after each turn

**Files:**
- Modify: `backend/app/api/routes_chat.py`
- Modify: `backend/tests/api/test_routes_chat.py`

- [ ] **Step 1: Write failing tests.** Append to `backend/tests/api/test_routes_chat.py`:

```python
from app.db.models import Event, SavedEvent


def _seed_events(db_session, ids: list[str]) -> None:
    for i, eid in enumerate(ids):
        db_session.add(Event(
            id=eid, external_id=f"x{i}", source="eventbrite",
            title=f"t{i}", category="music", source_url=f"http://{eid}",
            start_datetime=datetime(2026, 6, 14, tzinfo=timezone.utc),
        ))
    db_session.commit()


@patch("app.api.routes_chat.get_agent")
def test_chat_persists_recommendations_from_event_refs(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1", "e2"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (
            AIMessage(
                content="Try Jazz [event:e1] or Theatre [event:e2].",
                id="m1",
                response_metadata={"finish_reason": "stop"},
            ),
            {"langgraph_node": "agent"},
        )

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "what?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).filter_by(user_id="local").all()
    assert {(r.event_id, r.kind) for r in rows} == {
        ("e1", "recommendation"), ("e2", "recommendation"),
    }


@patch("app.api.routes_chat.get_agent")
def test_chat_skips_recommendations_when_setting_disabled(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    u = db_session.query(User).filter_by(id="local").one()
    u.settings = {"auto_recommendations_enabled": False}
    db_session.commit()

    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="Try [event:e1].", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    assert db_session.query(SavedEvent).count() == 0


@patch("app.api.routes_chat.get_agent")
def test_chat_skips_unknown_event_ids(mock_get_agent, client, user, db_session):
    _seed_events(db_session, ["e1"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="See [event:e1] and [event:ghost].", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).all()
    assert [r.event_id for r in rows] == ["e1"]


@patch("app.api.routes_chat.get_agent")
def test_chat_does_not_downgrade_already_saved_event(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    db_session.add(SavedEvent(id="pre", user_id="local", event_id="e1", kind="saved"))
    db_session.commit()

    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="[event:e1]", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    rows = db_session.query(SavedEvent).filter_by(event_id="e1").all()
    assert len(rows) == 1
    assert rows[0].kind == "saved"


@patch("app.api.routes_chat.get_agent")
def test_chat_recommendation_insert_is_idempotent_on_re_mention(
    mock_get_agent, client, user, db_session,
):
    _seed_events(db_session, ["e1"])
    fake_agent = MagicMock()
    _stub_agent_state(fake_agent)

    async def fake_astream(*args, **kwargs):
        yield (AIMessage(content="[event:e1] [event:e1]", id="m1",
                         response_metadata={"finish_reason": "stop"}),
               {"langgraph_node": "agent"})

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "?"}) as r:
        b"".join(r.iter_bytes())

    assert db_session.query(SavedEvent).filter_by(event_id="e1").count() == 1
```

Also at the top of the file add the missing import (only if not already present):

```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Run to confirm fail**

```bash
pytest tests/api/test_routes_chat.py::test_chat_persists_recommendations_from_event_refs -v
```
Expected: FAIL.

- [ ] **Step 3: Implement the helper + wiring.** In `backend/app/api/routes_chat.py`:

Add near the top imports:

```python
import re
import uuid

from app.db.models import Event, SavedEvent
```

(`User` and `ChatMessage` should already be imported.)

Add at module level after the imports:

```python
_EVENT_REF_RE = re.compile(r"\[event:([^\]]+)\]")


def _persist_recommendations(db, user_id: str, full_text: str) -> None:
    """Scrape [event:ID] refs from the assistant's final answer and insert
    a recommendation row for each. Idempotent: skips events already in the
    calendar (saved or recommendation), skips unknown IDs, no-ops when the
    user disabled the feature."""
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        return
    if not (user.settings or {}).get("auto_recommendations_enabled", True):
        return
    ids = list(dict.fromkeys(_EVENT_REF_RE.findall(full_text)))
    if not ids:
        return
    existing_event_ids = {
        row.id for row in db.query(Event.id).filter(Event.id.in_(ids)).all()
    }
    already_in_calendar = {
        row.event_id for row in db.query(SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids))
        .all()
    }
    added = False
    for eid in ids:
        if eid not in existing_event_ids or eid in already_in_calendar:
            continue
        db.add(SavedEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=eid,
            kind="recommendation",
        ))
        added = True
    if added:
        db.commit()
```

In `_stream_chat`, after `record_message(db, payload.session_id, user_id, "assistant", full_text)` and its `db.commit()`, add:

```python
        try:
            _persist_recommendations(db, user_id, full_text)
        except Exception:
            logger.exception("failed to persist recommendations")
```

Place this block before the final `yield {"event": "message", "data": json.dumps({"type": "done", ...})}`.

- [ ] **Step 4: Run tests**

```bash
pytest tests/api/test_routes_chat.py -v
```
Expected: all pass — old tests still green, new ones green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_chat.py backend/tests/api/test_routes_chat.py
git commit -m "feat(chat): auto-store [event:ID] refs as recommendations after each turn"
```

---

### Task 7: Run the full backend suite

- [ ] **Step 1: Run pytest**

From `backend/`:
```bash
pytest -q
```

Expected: all pass. If anything red is unrelated to this branch, fix or document. If red is related, fix before continuing.

- [ ] **Step 2: If any fixtures changed (e.g., User defaults), update them and re-run.** No commit needed if nothing was changed.

---

### Task 8: Frontend types

**Files:**
- Modify: `frontend/lib/types.ts`

- [ ] **Step 1: Apply edits.**

In `CalendarEntry`:
```ts
export interface CalendarEntry {
  id: string;
  event: EventCard;
  saved_at: string;
  kind: 'saved' | 'recommendation';
}
```

In `EventWithContext`:
```ts
export interface EventWithContext extends EventCard {
  user_sentiment: Sentiment | null;
  user_comment: string | null;
  is_saved: boolean;
  calendar_kind: 'saved' | 'recommendation' | null;
}
```

In `UserSettings`:
```ts
export interface UserSettings {
  tool_toggles: Record<string, boolean>;
  llm_provider: LLMProvider;
  llm_model: string | null;
  auto_recommendations_enabled: boolean;
}
```

In `SettingsUpdate`:
```ts
export interface SettingsUpdate {
  tool_toggles?: Record<string, boolean>;
  llm_provider?: LLMProvider;
  llm_model?: string | null;
  auto_recommendations_enabled?: boolean;
}
```

- [ ] **Step 2: Typecheck**

From `frontend/`:
```bash
npx tsc --noEmit
```
Expected: errors will appear in downstream files (they're fixed in later tasks). For now, just confirm the file compiles in isolation — skip the typecheck and let the next tasks make the whole project clean again.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(types): add kind, calendar_kind, auto_recommendations_enabled"
```

---

### Task 9: Frontend API client — slot-in + settings PUT

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/__tests__/api.test.ts` (test file; check existing patterns)

- [ ] **Step 1: Write failing tests.** Open `frontend/lib/__tests__/api.test.ts` and look at the existing patterns. Append two tests (mock `fetch` the same way the existing tests do):

```ts
import { slotInRecommendation, updateProfileSettings } from '@/lib/api'

describe('slotInRecommendation', () => {
  it('POSTs /calendar/{id}/slot-in', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ id: 'sav', event: { id: 'e1' }, saved_at: 'now', kind: 'saved' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    await slotInRecommendation('e1')
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\/calendar\/e1\/slot-in$/),
      expect.objectContaining({ method: 'POST' }),
    )
    fetchSpy.mockRestore()
  })
})

describe('updateProfileSettings', () => {
  it('PUTs /profile/settings with the partial body', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ city: 'Hamburg', interest_tags: [], about_me: null,
        taste_summary: null,
        settings: { tool_toggles: {}, llm_provider: 'openai', llm_model: null,
                    auto_recommendations_enabled: false } }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    await updateProfileSettings({ auto_recommendations_enabled: false })
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\/profile\/settings$/),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ auto_recommendations_enabled: false }),
      }),
    )
    fetchSpy.mockRestore()
  })
})
```

(Adapt the imports/Response wrapper to match the existing test file. If `api.test.ts` uses a different mock style, mirror that.)

- [ ] **Step 2: Run to confirm fail**

```bash
npm test -- api.test
```
Expected: FAIL (functions undefined).

- [ ] **Step 3: Implement.** In `frontend/lib/api.ts`, in the Calendar section, add after `removeFromCalendar`:

```ts
export async function slotInRecommendation(eventId: string): Promise<CalendarEntry> {
  if (MOCK) {
    console.info('[mock] POST /calendar/', eventId, '/slot-in')
    const detail = (await import('@/fixtures/event-detail.json')).default as EventWithContext
    const { user_sentiment, user_comment, is_saved, calendar_kind, ...card } = detail
    return { id: `sav_mock_${Date.now()}`, event: card, saved_at: new Date().toISOString(), kind: 'saved' }
  }
  return jsonFetch<CalendarEntry>(
    `/calendar/${encodeURIComponent(eventId)}/slot-in`,
    { method: 'POST' },
  )
}
```

In the Profile section, add:

```ts
export async function updateProfileSettings(body: SettingsUpdate): Promise<UserProfileResponse> {
  if (MOCK) {
    console.info('[mock] PUT /profile/settings', body)
    const current = (await import('@/fixtures/profile.json')).default as UserProfileResponse
    return {
      ...current,
      settings: { ...current.settings, ...body } as UserSettings,
    }
  }
  return jsonFetch<UserProfileResponse>('/profile/settings', {
    method: 'PUT', body: JSON.stringify(body),
  })
}
```

- [ ] **Step 4: Run tests**

```bash
npm test -- api.test
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/__tests__/api.test.ts
git commit -m "feat(api-client): slotInRecommendation, updateProfileSettings"
```

---

### Task 10: Calendar grid — recommendation discriminant

**Files:**
- Modify: `frontend/lib/calendarGrid.ts`
- Modify: `frontend/lib/__tests__/calendarGrid.test.ts`

- [ ] **Step 1: Write failing test.** Append to `frontend/lib/__tests__/calendarGrid.test.ts`:

```ts
import { toGridItem } from '@/lib/calendarGrid'
import type { CalendarEntry } from '@/lib/types'

describe('toGridItem recommendation', () => {
  it('returns kind="recommendation" when CalendarEntry.kind is "recommendation"', () => {
    const entry: CalendarEntry = {
      id: 'sav-1',
      saved_at: '2026-06-21T00:00:00Z',
      kind: 'recommendation',
      event: {
        id: 'evt-1', title: 'Jazz', summary: null,
        start_datetime: '2026-06-21T18:00:00Z',
        end_datetime: '2026-06-21T20:00:00Z',
        venue_name: null, venue_address: null,
        category: 'music', tags: [],
        price_min: null, price_max: null, is_free: true, currency: 'EUR',
        image_url: null, source_url: 'http://x', source: 's', is_active: true,
      },
    }
    const item = toGridItem({ kind: 'event', raw: entry })
    expect(item.kind).toBe('recommendation')
  })

  it('returns kind="event" when CalendarEntry.kind is "saved"', () => {
    const entry: CalendarEntry = {
      id: 'sav-2', saved_at: '2026-06-21T00:00:00Z', kind: 'saved',
      event: {
        id: 'evt-2', title: 'Talk', summary: null,
        start_datetime: '2026-06-21T18:00:00Z',
        end_datetime: '2026-06-21T20:00:00Z',
        venue_name: null, venue_address: null,
        category: 'tech', tags: [],
        price_min: null, price_max: null, is_free: true, currency: 'EUR',
        image_url: null, source_url: 'http://x', source: 's', is_active: true,
      },
    }
    expect(toGridItem({ kind: 'event', raw: entry }).kind).toBe('event')
  })
})
```

- [ ] **Step 2: Run to confirm fail**

```bash
npm test -- calendarGrid.test
```
Expected: FAIL.

- [ ] **Step 3: Apply edits.** In `frontend/lib/calendarGrid.ts`:

```ts
export interface GridItem {
  id: string
  kind: 'appointment' | 'event' | 'recommendation'
  title: string
  day: string
  startMinutes: number | null
  endMinutes: number | null
  raw: Appointment | CalendarEntry
}
```

In `toGridItem`, the event branch returns:

```ts
  const e: EventCard = input.raw.event
  const start = new Date(e.start_datetime)
  const end = e.end_datetime ? new Date(e.end_datetime) : null
  const kind: GridItem['kind'] = input.raw.kind === 'recommendation' ? 'recommendation' : 'event'
  return {
    id: e.id, kind, title: e.title, day: toLocalDayKey(start),
    startMinutes: minutesFromMidnight(start),
    endMinutes: end ? minutesFromMidnight(end) : null,
    raw: input.raw,
  }
```

- [ ] **Step 4: Run tests**

```bash
npm test -- calendarGrid.test
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/calendarGrid.ts frontend/lib/__tests__/calendarGrid.test.ts
git commit -m "feat(grid): propagate CalendarEntry.kind to GridItem"
```

---

### Task 11: EventBlock — recommendation styling

**Files:**
- Modify: `frontend/components/calendar/EventBlock.tsx`
- Create or modify: `frontend/components/__tests__/EventBlock.test.tsx`

- [ ] **Step 1: Write failing test.** Create `frontend/components/__tests__/EventBlock.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import EventBlock from '@/components/calendar/EventBlock'
import type { LaidOutItem } from '@/lib/calendarGrid'

const baseItem = (overrides: Partial<LaidOutItem>): LaidOutItem => ({
  id: 'evt-1', kind: 'event', title: 'Jazz Night', day: '2026-06-21',
  startMinutes: 18 * 60, endMinutes: 20 * 60,
  raw: {} as any,
  column: 0, columnCount: 1,
  ...overrides,
})

describe('EventBlock', () => {
  it('does not render Recommendation label for kind="event"', () => {
    render(<EventBlock item={baseItem({ kind: 'event' })} onClick={() => {}} />)
    expect(screen.queryByText(/Recommendation/i)).not.toBeInTheDocument()
  })

  it('renders gold "Recommendation:" label for kind="recommendation"', () => {
    render(<EventBlock item={baseItem({ id: 'rec-1', kind: 'recommendation' })} onClick={() => {}} />)
    expect(screen.getByText(/Recommendation:/i)).toBeInTheDocument()
  })

  it('applies data-kind="recommendation" attribute', () => {
    render(<EventBlock item={baseItem({ id: 'rec-1', kind: 'recommendation' })} onClick={() => {}} />)
    expect(screen.getByTestId('event-block-rec-1').dataset.kind).toBe('recommendation')
  })
})
```

- [ ] **Step 2: Run to confirm fail**

```bash
npm test -- EventBlock.test
```
Expected: FAIL.

- [ ] **Step 3: Apply edits.** Replace `frontend/components/calendar/EventBlock.tsx` with:

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

  const isRec = item.kind === 'recommendation'
  const borderColor =
    isRec ? 'border-text-muted' :
    item.kind === 'event' ? 'border-accent-gold' : 'border-text-secondary'
  const bgColor = isRec ? 'bg-gray-100' : 'bg-white'
  const titleClass = isRec ? 'text-text-secondary' : 'text-text-primary'

  return (
    <button
      data-testid={`event-block-${item.id}`}
      data-kind={item.kind}
      onClick={(e) => { e.stopPropagation(); onClick(item) }}
      style={{
        top: startPx, height: heightPx,
        left: `calc(${leftPct}% + 2px)`, width: `calc(${widthPct}% - 4px)`,
      }}
      className={`absolute z-10 text-left rounded-md ${bgColor} border border-border border-l-[3px] ${borderColor} px-2 py-1 overflow-hidden hover:shadow-sm`}
    >
      {isRec && (
        <p className="text-[9px] uppercase tracking-wider font-semibold text-accent-gold leading-none mb-0.5">
          Recommendation:
        </p>
      )}
      <p className={`text-[11px] font-semibold truncate ${titleClass}`}>{item.title}</p>
      <p className="text-[10px] text-text-muted">
        {fmtTime(item.startMinutes!)}{item.endMinutes != null ? ` – ${fmtTime(item.endMinutes)}` : ''}
      </p>
    </button>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
npm test -- EventBlock.test
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/calendar/EventBlock.tsx frontend/components/__tests__/EventBlock.test.tsx
git commit -m "feat(ui): render recommendation blocks with gray bg + gold label"
```

---

### Task 12: EventDetailOverlay — three-state action area

**Files:**
- Modify: `frontend/components/EventDetailOverlay.tsx`
- Modify: `frontend/components/__tests__/EventDetailOverlay.test.tsx`

The current overlay's `Props` accepts an `onSave(id, save: boolean)` callback only. For the recommendation state we need a separate `onSlotIn(id)` callback. Add it as a required new prop.

- [ ] **Step 1: Write failing tests.** Append to `frontend/components/__tests__/EventDetailOverlay.test.tsx`:

```tsx
const recommendationEvent: EventWithContext = {
  ...mockEvent, calendar_kind: 'recommendation', is_saved: true,
}

const savedEvent: EventWithContext = {
  ...mockEvent, calendar_kind: 'saved', is_saved: true,
}

const noEntryEvent: EventWithContext = {
  ...mockEvent, calendar_kind: null, is_saved: false,
}

describe('EventDetailOverlay action area', () => {
  it('shows only "Slot in" for noEntryEvent', () => {
    render(
      <EventDetailOverlay event={noEntryEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot in$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Slot out$/i })).not.toBeInTheDocument()
  })

  it('shows only "Slot Out" for savedEvent', () => {
    render(
      <EventDetailOverlay event={savedEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot Out$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Slot in$/i })).not.toBeInTheDocument()
  })

  it('shows both buttons for recommendationEvent', () => {
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot in$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Slot out$/i })).toBeInTheDocument()
  })

  it('calls onSlotIn(id) when slot-in clicked on a recommendation', () => {
    const onSlotIn = vi.fn()
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={onSlotIn} />
    )
    fireEvent.click(screen.getByRole('button', { name: /^Slot in$/i }))
    expect(onSlotIn).toHaveBeenCalledWith('evt_001')
  })

  it('calls onSave(id, false) when slot-out clicked on a recommendation', () => {
    const onSave = vi.fn()
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={onSave} onSlotIn={vi.fn()} />
    )
    fireEvent.click(screen.getByRole('button', { name: /^Slot out$/i }))
    expect(onSave).toHaveBeenCalledWith('evt_001', false)
  })
})
```

Also update the existing `mockEvent` at the top of the file to include `calendar_kind: null`:

```ts
const mockEvent: EventWithContext = {
  // ... existing fields ...
  user_sentiment: null, user_comment: null, is_saved: false,
  calendar_kind: null,
}
```

And update each existing render call that passed `onSave={vi.fn()}` to also pass `onSlotIn={vi.fn()}`.

- [ ] **Step 2: Run to confirm fail**

```bash
npm test -- EventDetailOverlay.test
```
Expected: FAIL (Props mismatch + missing buttons).

- [ ] **Step 3: Apply edits to `frontend/components/EventDetailOverlay.tsx`.**

Update the `Props` interface:

```ts
interface Props {
  event: EventWithContext
  justification: string | null
  onClose: () => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  onSave: (id: string, save: boolean) => void
  onSlotIn: (id: string) => void
}
```

Update the function signature in `OverlayContent`:

```ts
function OverlayContent({ event, justification, onClose, onFeedback, onSave, onSlotIn }: Props) {
```

Update the `EventDetailOverlay` default export to forward the new prop (it already spreads `props`, no change needed if you keep `<OverlayContent {...props} />`).

Replace the action-area block (currently the three feedback buttons + one save toggle) with kind-aware rendering. Find the block:

```tsx
          <div className="ml-auto flex gap-1.5 items-center">
            <button aria-label="Like" ...>👍</button>
            <button aria-label="Dislike" ...>👎</button>
            <button onClick={() => onSave(event.id, !isSaved)} ...>
              {isSaved ? 'Slot Out' : 'Slot in'}
            </button>
          </div>
```

Add a derivation right above this block (after the existing `const optSaved`/`isSaved` lines), prefer `calendar_kind` for the three-state decision:

```tsx
  // calendar_kind drives the action area; fall back to is_saved when the
  // server omitted it (e.g., older mocks).
  const calendarKind: 'saved' | 'recommendation' | null =
    event.calendar_kind ?? (isSaved ? 'saved' : null)
```

Replace the save button with:

```tsx
            {calendarKind === 'recommendation' ? (
              <>
                <button
                  onClick={() => onSlotIn(event.id)}
                  className="rounded text-[11px] font-semibold px-3 py-1 bg-accent-gold text-bg-page"
                >
                  Slot in
                </button>
                <button
                  onClick={() => onSave(event.id, false)}
                  className="rounded text-[11px] font-semibold px-3 py-1 border border-accent-gold text-accent-gold bg-transparent"
                >
                  Slot out
                </button>
              </>
            ) : (
              <button
                onClick={() => onSave(event.id, calendarKind !== 'saved')}
                className={`rounded text-[11px] font-semibold px-3 py-1 ${
                  calendarKind === 'saved'
                    ? 'bg-accent-gold-light text-accent-gold'
                    : 'bg-accent-gold text-bg-page'
                }`}
              >
                {calendarKind === 'saved' ? 'Slot Out' : 'Slot in'}
              </button>
            )}
```

- [ ] **Step 4: Run tests**

```bash
npm test -- EventDetailOverlay.test
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/EventDetailOverlay.tsx frontend/components/__tests__/EventDetailOverlay.test.tsx
git commit -m "feat(ui): three-state action area in EventDetailOverlay"
```

---

### Task 13: AppShell — `handleSlotIn` + clear both override maps on slot-out

**Files:**
- Modify: `frontend/components/AppShell.tsx`

This task adds a third optimistic-update path. The existing `handleSave(id, false)` flips `is_saved`; on a recommendation slot-out we also need `calendar_kind` to clear to `null`. We add a third override map (`optCalendarKind`) and a `handleSlotIn` callback, and adjust `handleSave` to write to both maps when called.

- [ ] **Step 1: Apply edits to `frontend/components/AppShell.tsx`.**

Add the new imports:

```ts
import { slotInRecommendation } from '@/lib/api'
```

Extend the context value:

```ts
interface AppShellCtxValue {
  openOverlay: (eventId: string, justification?: string | null) => void
  handleSave: (eventId: string, shouldBeSaved: boolean) => Promise<void>
  handleSlotIn: (eventId: string) => Promise<void>
  handleFeedback: (eventId: string, sentiment: Sentiment | null) => Promise<void>
  isOptimisticallySaved: (eventId: string) => boolean | undefined
  optimisticSentimentFor: (eventId: string) => Sentiment | null | undefined
  optimisticCalendarKindFor: (eventId: string) => 'saved' | 'recommendation' | null | undefined
}
```

In `Shell`, add the new state:

```ts
  const [optCalendarKind, setOptCalendarKind] = useState<Map<string, 'saved' | 'recommendation' | null>>(new Map())
```

Update `handleSave` to also clear `optCalendarKind` to `null` when the user unsaves (rollback also clears it):

```ts
  const handleSave = useCallback(async (eventId: string, shouldBeSaved: boolean) => {
    setOptSaved((m) => new Map(m).set(eventId, shouldBeSaved))
    if (!shouldBeSaved) {
      setOptCalendarKind((m) => new Map(m).set(eventId, null))
    } else {
      setOptCalendarKind((m) => new Map(m).set(eventId, 'saved'))
    }
    try {
      if (shouldBeSaved) await saveToCalendar(eventId)
      else                await removeFromCalendar(eventId)
      fanOutEventCaches(eventId)
    } catch {
      setOptSaved((m) => { const n = new Map(m); n.delete(eventId); return n })
      setOptCalendarKind((m) => { const n = new Map(m); n.delete(eventId); return n })
    }
  }, [fanOutEventCaches])
```

Add `handleSlotIn`:

```ts
  const handleSlotIn = useCallback(async (eventId: string) => {
    setOptSaved((m) => new Map(m).set(eventId, true))
    setOptCalendarKind((m) => new Map(m).set(eventId, 'saved'))
    try {
      await slotInRecommendation(eventId)
      fanOutEventCaches(eventId)
    } catch {
      setOptSaved((m) => { const n = new Map(m); n.delete(eventId); return n })
      setOptCalendarKind((m) => { const n = new Map(m); n.delete(eventId); return n })
    }
  }, [fanOutEventCaches])
```

Add the selector:

```ts
  const optimisticCalendarKindFor = useCallback(
    (eventId: string) =>
      optCalendarKind.has(eventId) ? optCalendarKind.get(eventId) : undefined,
    [optCalendarKind],
  )
```

Extend the `AppShellCtx.Provider` value:

```tsx
    <AppShellCtx.Provider
      value={{
        openOverlay, handleSave, handleSlotIn, handleFeedback,
        isOptimisticallySaved, optimisticSentimentFor, optimisticCalendarKindFor,
      }}
    >
```

Pass `handleSlotIn` into `EventDetailOverlayLoader`:

```tsx
      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          justification={activeJustification}
          onClose={closeOverlay}
          onSave={handleSave}
          onSlotIn={handleSlotIn}
          onFeedback={handleFeedback}
        />
      )}
```

Add the prop on `EventDetailOverlayLoader`:

```tsx
function EventDetailOverlayLoader({
  eventId, justification, onClose, onSave, onSlotIn, onFeedback,
}: {
  eventId: string
  justification: string | null
  onClose: () => void
  onSave: (id: string, save: boolean) => void
  onSlotIn: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
}) {
  const { data: event } = useSWR(`/events/${eventId}`, () => getEventDetail(eventId))
  if (!event) return null
  return (
    <EventDetailOverlay
      event={event}
      justification={justification}
      onClose={onClose}
      onFeedback={onFeedback}
      onSave={onSave}
      onSlotIn={onSlotIn}
    />
  )
}
```

Wire `optimisticCalendarKindFor` into `EventDetailOverlay` so the displayed kind reflects optimistic transitions. In `EventDetailOverlay.tsx::OverlayContent`, replace `calendarKind` derivation with:

```tsx
  const { isOptimisticallySaved, optimisticSentimentFor, optimisticCalendarKindFor, openOverlay } = useAppShell()
  const optSent = optimisticSentimentFor(event.id)
  const sentiment: Sentiment | null = optSent !== undefined ? optSent : (event.user_sentiment ?? null)
  const optSaved = isOptimisticallySaved(event.id)
  const isSaved = optSaved !== undefined ? optSaved : event.is_saved
  const optKind = optimisticCalendarKindFor(event.id)
  const calendarKind: 'saved' | 'recommendation' | null =
    optKind !== undefined ? optKind : (event.calendar_kind ?? (isSaved ? 'saved' : null))
```

Also update the `useAppShell` mock at the top of `EventDetailOverlay.test.tsx` (in Task 12 you've already touched this file — re-edit to add the new selector):

```ts
vi.mock('@/components/AppShell', () => ({
  useAppShell: vi.fn(() => ({
    isOptimisticallySaved: vi.fn(() => undefined),
    optimisticSentimentFor: vi.fn(() => undefined),
    optimisticCalendarKindFor: vi.fn(() => undefined),
    openOverlay: vi.fn(),
  })),
}))
```

- [ ] **Step 2: Run all frontend tests**

```bash
npm test
```
Expected: pass — EventDetailOverlay tests still green; AppShell-using suites untouched.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/AppShell.tsx frontend/components/EventDetailOverlay.tsx frontend/components/__tests__/EventDetailOverlay.test.tsx
git commit -m "feat(ui): handleSlotIn + calendar_kind optimistic override in AppShell"
```

---

### Task 14: Settings page + TopNav link

**Files:**
- Create: `frontend/app/settings/page.tsx`
- Create: `frontend/components/__tests__/SettingsPage.test.tsx`
- Modify: `frontend/components/TopNav.tsx`
- Modify: `frontend/components/AppShell.tsx`
- Modify: `frontend/components/__tests__/TopNav.test.tsx`

- [ ] **Step 1: Write failing test for the settings page.** Create `frontend/components/__tests__/SettingsPage.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import SettingsPage from '@/app/settings/page'

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
  return {
    ...actual,
    getProfile: vi.fn(async () => ({
      city: 'Hamburg', interest_tags: [], about_me: null, taste_summary: null,
      settings: {
        tool_toggles: {}, llm_provider: 'openai', llm_model: null,
        auto_recommendations_enabled: true,
      },
    })),
    updateProfileSettings: vi.fn(async (b) => ({
      city: 'Hamburg', interest_tags: [], about_me: null, taste_summary: null,
      settings: {
        tool_toggles: {}, llm_provider: 'openai', llm_model: null,
        auto_recommendations_enabled: b.auto_recommendations_enabled,
      },
    })),
  }
})

function wrap(node: React.ReactNode) {
  return <SWRConfig value={{ provider: () => new Map() }}>{node}</SWRConfig>
}

describe('SettingsPage', () => {
  it('renders the auto-recommendations toggle', async () => {
    render(wrap(<SettingsPage />))
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /Add recommendations/i })).toBeInTheDocument()
    })
  })

  it('toggle is checked when auto_recommendations_enabled=true', async () => {
    render(wrap(<SettingsPage />))
    const toggle = await screen.findByRole('checkbox', { name: /Add recommendations/i })
    expect(toggle).toBeChecked()
  })

  it('clicking the toggle calls updateProfileSettings with the new value', async () => {
    const { updateProfileSettings } = await import('@/lib/api')
    render(wrap(<SettingsPage />))
    const toggle = await screen.findByRole('checkbox', { name: /Add recommendations/i })
    fireEvent.click(toggle)
    await waitFor(() => {
      expect(updateProfileSettings).toHaveBeenCalledWith({ auto_recommendations_enabled: false })
    })
  })
})
```

- [ ] **Step 2: Run to confirm fail**

```bash
npm test -- SettingsPage.test
```
Expected: FAIL (page does not exist).

- [ ] **Step 3: Create the page.** Write `frontend/app/settings/page.tsx`:

```tsx
'use client'
import useSWR, { useSWRConfig } from 'swr'
import { getProfile, updateProfileSettings } from '@/lib/api'
import type { UserProfileResponse } from '@/lib/types'

export default function SettingsPage() {
  const { mutate } = useSWRConfig()
  const { data: profile, isLoading } = useSWR<UserProfileResponse>('/profile', getProfile)

  async function onToggleAutoRec(next: boolean) {
    const updated = await updateProfileSettings({ auto_recommendations_enabled: next })
    mutate('/profile', updated, { revalidate: false })
  }

  return (
    <main className="flex-1 overflow-y-auto px-6 py-6 bg-bg-page">
      <h1 className="font-serif font-bold text-lg text-text-primary mb-4">Settings</h1>
      <section className="rounded-lg border border-border bg-white p-4 max-w-xl">
        <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">AI Assistant</h2>
        {isLoading || !profile ? (
          <p className="text-[12px] text-text-muted">Loading…</p>
        ) : (
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              aria-label="Add recommendations to my timetable automatically"
              checked={profile.settings.auto_recommendations_enabled}
              onChange={(e) => onToggleAutoRec(e.target.checked)}
              className="mt-1 h-4 w-4 accent-accent-gold"
            />
            <span className="flex flex-col">
              <span className="text-[13px] font-semibold text-text-primary">
                Add recommendations to my timetable automatically
              </span>
              <span className="text-[11px] text-text-muted mt-0.5">
                When on, events the AI assistant mentions appear in your timetable as gray
                &quot;Recommendation&quot; blocks until you slot them in or out.
              </span>
            </span>
          </label>
        )}
      </section>
    </main>
  )
}
```

- [ ] **Step 4: Add the TopNav entry.** Replace `frontend/components/TopNav.tsx`:

```tsx
import Link from 'next/link'

type ActivePage = 'timetable' | 'explore' | 'settings'

const LINKS: { href: string; label: string; page: ActivePage }[] = [
  { href: '/',         label: 'Timetable', page: 'timetable' },
  { href: '/explore',  label: 'Explore',   page: 'explore'   },
  { href: '/settings', label: 'Settings',  page: 'settings'  },
]

export default function TopNav({ active, date }: { active: ActivePage; date: string }) {
  return (
    <nav className="sticky top-0 z-30 flex items-center gap-1 px-5 py-2.5 bg-bg-surface border-b border-border">
      <span className="font-serif font-bold text-base text-text-primary mr-5">
        SlotIn
      </span>
      {LINKS.map(({ href, label, page }) => (
        <Link
          key={page}
          href={href}
          className={
            page === active
              ? 'rounded px-3 py-1 text-xs font-semibold bg-accent-gold text-bg-page'
              : 'rounded px-3 py-1 text-xs text-text-secondary hover:text-text-primary'
          }
        >
          {label}
        </Link>
      ))}
      <span className="ml-auto text-xs italic text-accent-gold">{date}</span>
    </nav>
  )
}
```

- [ ] **Step 5: Update AppShell active derivation.** In `frontend/components/AppShell.tsx`, inside `Shell`, replace the `active` line:

```ts
  const active: 'timetable' | 'explore' | 'settings' =
    pathname?.startsWith('/explore') ? 'explore'
    : pathname?.startsWith('/settings') ? 'settings'
    : 'timetable'
```

- [ ] **Step 6: Update TopNav test.** Open `frontend/components/__tests__/TopNav.test.tsx` and ensure existing tests still pass — they probably typed `ActivePage` as `'timetable' | 'explore'`. If a test passes `active="settings"` is missing, add a quick assertion that the settings link is rendered:

```tsx
it('renders Settings link', () => {
  render(<TopNav active="timetable" date="Hamburg" />)
  expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument()
})
```

- [ ] **Step 7: Run all frontend tests**

```bash
npm test
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/settings/page.tsx frontend/components/TopNav.tsx frontend/components/AppShell.tsx frontend/components/__tests__/SettingsPage.test.tsx frontend/components/__tests__/TopNav.test.tsx
git commit -m "feat(ui): settings page with auto-recommendations toggle"
```

---

### Task 15: Full test suite + smoke

- [ ] **Step 1: Backend pytest**

From `backend/`:
```bash
pytest -q
```
Expected: all green.

- [ ] **Step 2: Frontend tests**

From `frontend/`:
```bash
npm test -- --run
```
Expected: all green.

- [ ] **Step 3: TypeScript check**

```bash
npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Manual smoke (optional but recommended).**

1. Start backend (`uvicorn app.main:app --reload`) and frontend (`npm run dev`).
2. In the chat panel, ask: "Find a jazz event this weekend".
3. Verify: after the reply renders, gray "Recommendation:" blocks appear in the timetable for the mentioned events.
4. Click one → overlay shows "Slot in" + "Slot out".
5. Slot in → block changes to gold styling.
6. Repeat, slot out → block disappears.
7. Go to Settings, toggle the feature off.
8. New chat with event refs → no new recommendation blocks appear.

- [ ] **Step 5: Final commit if any docs/notes changed.** None expected.

---

## Self-review notes

The plan covers every spec requirement:

- ✅ `kind` column + migration → Task 1
- ✅ `CalendarEntry.kind` on `/calendar` → Task 2
- ✅ `POST /calendar/{id}/slot-in` → Task 3
- ✅ `calendar_kind` on `/events/{id}` → Task 4
- ✅ `auto_recommendations_enabled` setting + `PUT /profile/settings` → Task 5
- ✅ Chat hook persistence + idempotency + skip-already-saved + setting respect → Task 6
- ✅ Frontend types → Task 8
- ✅ API client functions → Task 9
- ✅ Grid `kind` discriminant → Task 10
- ✅ EventBlock recommendation styling → Task 11
- ✅ EventDetailOverlay three-state action area → Task 12
- ✅ AppShell handleSlotIn + slot-out clears both override maps → Task 13
- ✅ Settings page + TopNav → Task 14

**Deviation from spec:** the spec said add a column on `users` for the toggle. The plan stores it inside the existing `users.settings` JSON dict instead — same persistence guarantees, no migration on `users`. The `UserSettings` Pydantic schema already centralises this surface.
