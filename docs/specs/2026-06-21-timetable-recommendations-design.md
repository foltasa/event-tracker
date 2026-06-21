# Timetable Recommendations — Design

Status: approved
Date: 2026-06-21
Branch: feature/timetable-recommendations

## Goal

After any chat turn that mentions events, the AI assistant's referenced events
should automatically appear in the user's timetable as a new kind of entry
called a **recommendation**. Recommendations look visually distinct from saved
events and can be either accepted (slot in → become a regular saved event) or
dismissed (slot out → removed). A user setting controls whether the feature is
on (default on).

Optimisation of *which* events the AI surfaces — by user taste, availability,
or any other signal — is explicitly **out of scope**. This feature is the
plumbing that lets agent suggestions land in the timetable; it does not change
what the agent suggests.

## User-visible behaviour

1. The user sends any chat message that causes the assistant to mention one or
   more events (the assistant already inlines events as `[event:ID]`).
2. After the reply is rendered, each mentioned event appears in the weekly
   timetable at its scheduled date/time as a light-gray block with a small
   gold **"Recommendation:"** label above the event title.
3. Clicking a recommendation opens the existing event detail overlay. The
   overlay's action area shows two buttons side-by-side: **Slot in** (gold,
   primary) and **Slot out** (outlined, secondary).
4. Slot in flips the entry to a regular saved event (gold styling, just like
   today's saved events). Slot out removes the entry from the timetable
   entirely.
5. A setting on a new Settings page toggles the auto-add behaviour on/off.
   Default: on.

## Data model

### `saved_events` (extended)

Add a column:

| Column | Type | Notes |
|--------|------|-------|
| `kind` | `TEXT NOT NULL` | `'saved'` or `'recommendation'`. Default `'saved'`. |

Alembic migration `0005_saved_event_kind.py`:
- adds the column with a default of `'saved'`;
- backfills existing rows to `'saved'` (covered by the default);
- no index needed at MVP scale.

The existing `UniqueConstraint('user_id', 'event_id')` continues to apply.
That means a `(user, event)` pair has at most one row regardless of kind — when
the chat hook is about to insert a recommendation but a row already exists,
the row is left alone (idempotent in both directions: an already-saved event
is not downgraded; an already-recommended event is not duplicated).

### `users` (extended)

| Column | Type | Notes |
|--------|------|-------|
| `auto_recommendations_enabled` | `BOOLEAN NOT NULL` | Default `TRUE`. |

Alembic migration `0006_user_auto_recommendations.py` adds the column with a
server default of true so existing users opt in.

## Backend API

### `GET /calendar`

Existing endpoint. Response schema (`CalendarEntry`) gains a `kind` field:

```python
class CalendarEntry(BaseModel):
    id: str
    event: EventCard
    saved_at: datetime
    kind: Literal["saved", "recommendation"]
```

### `POST /calendar/{event_id}/slot-in` (new)

Promotes a recommendation row to a saved one for the current user.

- 200 → returns the updated `CalendarEntry` with `kind='saved'`.
- 404 → no row exists for `(user, event_id)`.
- Idempotent: if the row already has `kind='saved'`, return it unchanged.

### `DELETE /calendar/{event_id}`

Existing endpoint. Already removes the row regardless of kind. The frontend
uses this for "Slot out" on a recommendation and for "Slot Out" on a saved
event — single endpoint, two UX surfaces.

### `GET /events/{event_id}` (extended)

The response shape (`EventWithContext`) gains:

```python
calendar_kind: Literal["saved", "recommendation"] | None
```

Computed as: the `SavedEvent.kind` if a row exists for `(current_user,
event_id)`, else `None`. `is_saved` remains as it is today (true iff *any*
row exists, recommendation or saved). The overlay uses `calendar_kind` to
decide which button(s) to render.

### `PATCH /profile/settings` (extended)

The `UserSettings` shape gains:

```python
auto_recommendations_enabled: bool
```

The `GET /profile` response includes it (it lives inside the existing
`settings` block). The settings page reads and writes it via this route.

## Chat → recommendations hook

In `app/api/routes_chat.py::_stream_chat`, after the assistant's `full_text` is
assembled (just before the `done` event is yielded) and after the assistant
message is persisted:

1. Skip if `user.auto_recommendations_enabled` is false. Done.
2. Extract event IDs from `full_text` using the same `[event:ID]` pattern that
   `frontend/lib/parseMessageContent.ts` already recognises.
3. For each unique ID:
   - Verify the event exists; skip otherwise.
   - Skip if a `SavedEvent` row already exists for `(user, event_id)`
     (preserves both already-saved and already-recommended rows).
   - Insert a new `SavedEvent(user_id, event_id, kind='recommendation')`.
4. Commit. Failures here are logged but do not affect the chat stream — the
   user already saw the reply.

The hook fires for every chat session, including the per-event chat
(`event_<id>`). The mentioned events flow through the same idempotency check,
so re-mentioning an event the user is currently viewing is a no-op.

### Pseudocode

```python
import re
EVENT_REF_RE = re.compile(r"\[event:([^\]]+)\]")

def _persist_recommendations(db, user_id: str, full_text: str) -> None:
    user = db.query(User).filter_by(id=user_id).one()
    if not user.auto_recommendations_enabled:
        return
    ids = list(dict.fromkeys(EVENT_REF_RE.findall(full_text)))
    if not ids:
        return
    existing_event_ids = {
        e.id for e in db.query(Event.id).filter(Event.id.in_(ids)).all()
    }
    already_in_calendar = {
        r.event_id for r in db.query(SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids))
        .all()
    }
    for eid in ids:
        if eid not in existing_event_ids:
            continue
        if eid in already_in_calendar:
            continue
        db.add(SavedEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=eid,
            kind="recommendation",
        ))
    db.commit()
```

## Frontend

### Types

`frontend/lib/types.ts`:

```ts
export interface CalendarEntry {
  id: string;
  event: EventCard;
  saved_at: string;
  kind: 'saved' | 'recommendation';
}

export interface EventWithContext extends EventCard {
  user_sentiment: Sentiment | null;
  user_comment: string | null;
  is_saved: boolean;
  calendar_kind: 'saved' | 'recommendation' | null;
}

export interface UserSettings {
  tool_toggles: Record<string, boolean>;
  llm_provider: LLMProvider;
  llm_model: string | null;
  auto_recommendations_enabled: boolean;
}
```

### Grid layout

`frontend/lib/calendarGrid.ts`: extend the `GridItem.kind` discriminant from
`'appointment' | 'event'` to `'appointment' | 'event' | 'recommendation'`.
`toGridItem` reads `CalendarEntry.kind` and produces `kind: 'recommendation'`
when appropriate, else `'event'`. All overlap/column logic continues unchanged
— recommendations participate in column layout exactly like events.

### `EventBlock`

When `item.kind === 'recommendation'`:

- Container: `bg-gray-100` (light gray) instead of `bg-white`.
- Left border: `border-text-muted` instead of `border-accent-gold`.
- Above the title: a small label `Recommendation:` in
  `text-[10px] uppercase tracking-wider text-accent-gold` — same styling as
  the meta labels used elsewhere in the UI.
- Title and time use `text-text-secondary` for reduced contrast.

### Click handling

`frontend/app/page.tsx::onItemClick`: both `'event'` and `'recommendation'`
open the overlay via `openOverlay(item.id)`. The overlay branches internally on
`calendar_kind`.

### `EventDetailOverlay`

The meta row's action area branches on `event.calendar_kind`:

| `calendar_kind` | Buttons |
|---|---|
| `null` | Single `Slot in` (gold) → calls `handleSave(id, true)`. |
| `'saved'` | Single `Slot Out` (gold-light) → calls `handleSave(id, false)`. |
| `'recommendation'` | Two buttons: `Slot in` (gold) → `handleSlotIn(id)`; `Slot out` (outline) → `handleSave(id, false)`. |

After slot-in the overlay stays open and re-renders in the `'saved'` state.
After slot-out (from either state) the overlay closes — matching today's
unsaved flow.

### `AppShell` wiring

Add a third callback `handleSlotIn(eventId)` alongside `handleSave` and
`handleFeedback`. It:

1. Optimistically sets `calendar_kind` → `'saved'` AND `is_saved` → `true` in
   override maps (extends the existing optimistic-save infrastructure with a
   `calendar_kind` override map).
2. Calls `POST /calendar/{eventId}/slot-in`.
3. On success, fans out cache invalidations (`/calendar`, `/events/{id}`,
   `/digest`, lists, appointments) — same fan-out as `handleSave`.
4. On failure, rolls back the override.

The existing `handleSave(id, false)` already covers slot-out from both saved
and recommendation states because `DELETE /calendar/{id}` deletes either kind.
On a recommendation slot-out, the optimistic update must clear *both*
`calendar_kind` (→ `null`) and `is_saved` (→ `false`) so the overlay closes
cleanly and the timetable removes the block.

### Settings page (new)

Route: `frontend/app/settings/page.tsx`.

Layout: a single labelled section titled "AI Assistant" with one toggle:

- Label: **Add recommendations to my timetable automatically**
- Hint: *"When on, events the AI assistant mentions appear in your timetable
  as gray 'Recommendation' blocks until you slot them in or out."*
- Default state: on.

Data flow: SWR-loads `GET /profile`; toggle reads
`profile.settings.auto_recommendations_enabled`; on change calls
`PATCH /profile/settings` with `{ auto_recommendations_enabled }`. Optimistic
update via SWR's `mutate`.

### `TopNav`

Add a third nav target — `settings` — with a gear icon. `AppShell.Shell`
extends its `active` derivation:

```ts
const active: 'timetable' | 'explore' | 'settings' =
  pathname?.startsWith('/explore') ? 'explore'
  : pathname?.startsWith('/settings') ? 'settings'
  : 'timetable'
```

## Tests

### Backend

- Migration smoke: column added with default `'saved'`; existing rows
  backfilled.
- `POST /calendar/{id}/slot-in`:
  - flips a recommendation row to saved;
  - is idempotent on an already-saved row;
  - returns 404 when no row exists.
- Chat hook (`_persist_recommendations`):
  - inserts each `[event:ID]` as `kind='recommendation'`;
  - skips IDs not present in `events`;
  - skips IDs already in `saved_events` regardless of current kind;
  - re-mentioning an existing recommendation is a no-op;
  - does nothing when `auto_recommendations_enabled=false`;
  - end-to-end: a mocked agent reply containing two valid `[event:ID]`
    references results in two recommendation rows.
- `GET /events/{id}` returns `calendar_kind` correctly for the three states.
- `PATCH /profile/settings` round-trips `auto_recommendations_enabled`.

### Frontend

- `EventBlock`:
  - renders the gray container, muted border, and gold "Recommendation:"
    label when `kind='recommendation'`;
  - renders unchanged for `'event'` and `'appointment'`.
- `EventDetailOverlay`:
  - shows one `Slot in` button when `calendar_kind=null`;
  - shows one `Slot Out` button when `calendar_kind='saved'`;
  - shows both `Slot in` and `Slot out` buttons when
    `calendar_kind='recommendation'`;
  - clicking `Slot in` on a recommendation calls the slot-in endpoint and
    optimistically transitions both `calendar_kind` and `is_saved`;
  - clicking `Slot out` on a recommendation calls DELETE and optimistically
    clears both override fields.
- Settings page: toggle reads from `/profile`, writes through
  `/profile/settings`, and persists across reloads.

## Out of scope

- Ranking, dedup, or filtering of recommendations against the user's taste
  vector or availability.
- Capturing or surfacing per-recommendation justifications.
- Auto-expiry / cleanup of past-dated recommendations.
- Web-search and digest routes do not run the recommendation hook in this
  iteration; only the conversational chat route does.
- Per-event chat sessions are *not* excluded from the hook — any chat turn
  that produces `[event:ID]` references triggers the same write path. The
  idempotency check makes this safe (the event the user is currently viewing
  cannot be auto-recommended into the calendar twice, and won't be downgraded
  if already saved).
