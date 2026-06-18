# Calendar Week-View Design

**Date:** 2026-06-16
**Branch:** feat/calendar
**Status:** Approved

---

## Overview

Replace the small month-grid calendar (`frontend/app/calendar/page.tsx`) with a full-column week view modeled on Google Calendar. The new view:

1. Fills the entire content column to the left of the chat panel; produces its own scrollbars when content overflows.
2. Shows seven day columns (Monday–Sunday) over a 24-hour vertical grid, with a horizontal "now" line in today's column.
3. Adds **user-created appointments** as a new first-class concept (new backend table, routes, and SQLAlchemy model).
4. Adds a click-to-create modal with two tabs: **Make an appointment** and **Recommend me something** (placeholder).
5. Seeds the default user with a "Turing College" appointment 09:00–16:30 for every weekday of June and July 2026.

Custom appointments and saved feed events render through the same grid renderer using a normalized item shape.

---

## Section 1: Backend — data model, routes, seed

### New table `appointments`

Alembic migration `0004_appointments.py`:

| column       | type                  | notes                                |
| ------------ | --------------------- | ------------------------------------ |
| `id`         | String PK             | UUID                                 |
| `user_id`    | String FK → users.id  | not nullable                         |
| `title`      | String                | not nullable                         |
| `day`        | Date                  | not nullable — anchor day            |
| `start_at`   | DateTime(timezone)    | nullable                             |
| `end_at`     | DateTime(timezone)    | nullable                             |
| `created_at` | DateTime(timezone)    | default `utcnow`                     |

Index on `(user_id, day)` for week-range queries.

### Semantics

| `start_at` | `end_at` | meaning                                            |
| ---------- | -------- | -------------------------------------------------- |
| null       | null     | all-day on `day`                                   |
| set        | null     | from `start_at` to end of `day` (24:00)            |
| set        | set      | timed; may cross midnight (`end_at` on next day)   |
| null       | set      | rejected at API (400)                              |

This mirrors `Event.end_datetime` (already nullable), so saved feed events and custom appointments share the same "missing end → end of day" rendering rule.

### ORM model

`backend/app/db/models/appointment.py` mirrors the style of `SavedEvent`. Re-export it in `backend/app/db/models/__init__.py`.

### Pydantic schemas

`backend/app/schemas/appointment.py`:

- `Appointment` (read shape): `id`, `title`, `day`, `start_at`, `end_at`, `created_at`.
- `AppointmentCreate`: `title`, `day`, `start_at`, `end_at`.
  Validator rejects `start_at is None and end_at is not None`.
  Validator rejects `end_at <= start_at` when both fall on the same calendar day.
- `AppointmentUpdate`: every field on `AppointmentCreate` optional; same validators apply when the relevant fields are present.
- `AppointmentsResponse`: `{ appointments: list[Appointment] }`.

### REST routes

`backend/app/api/routes_appointments.py`, mounted at `/appointments`:

- `GET /appointments?from=YYYY-MM-DD&to=YYYY-MM-DD` — list current user's appointments where `day` falls in `[from, to]`. Defaults to today ± 90 days when params are omitted. Ordered by `day, start_at NULLS FIRST`.
- `POST /appointments` — body `AppointmentCreate`, returns `Appointment`.
- `PATCH /appointments/{id}` — body `AppointmentUpdate`, returns `Appointment`. 404 if not owned by current user.
- `DELETE /appointments/{id}` — 204. 404 if not owned by current user.
- `POST /appointments/recommend` — body `{ day: str, start_at: str | null, end_at: str | null, message: str }`. Returns `{ message: "Currently not implemented" }`. Placeholder; no DB writes.

All routes scoped via `get_current_user_id()` following existing pattern.

### Seed script

`backend/scripts/seed_default_appointments.py`:

- Resolves the default user via the same helper used by dev runs.
- Inserts a "Turing College" appointment for every weekday (Mon–Fri) of June and July 2026 — 45 rows (22 in June + 23 in July).
- Times: 09:00–16:30 local time (Hamburg, the city in `UserProfileResponse`), converted to timezone-aware UTC.
- Idempotent: queries for an existing `Appointment` with the same `user_id`, `title="Turing College"`, and `day`, and skips if present.
- Run with `python -m scripts.seed_default_appointments` from `backend/`.

---

## Section 2: Frontend — types and API layer

### Types (`frontend/lib/types.ts`)

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
```

### API functions (`frontend/lib/api.ts`)

```ts
listAppointments(from: string, to: string): Promise<AppointmentsResponse>
createAppointment(payload: AppointmentCreate): Promise<Appointment>
updateAppointment(id: string, payload: AppointmentUpdate): Promise<Appointment>
deleteAppointment(id: string): Promise<void>
recommendAppointment(payload: {
  day: string;
  start_at: string | null;
  end_at: string | null;
  message: string;
}): Promise<{ message: string }>
```

### SWR keys

- `['/appointments', weekStartISO, weekEndISO]` — custom appointments for the visible week.
- `/calendar` — existing; saved feed events. Filtered client-side to the visible week.

After any appointment mutation, `AppShell.fanOutEventCaches` revalidates both. One new line:

```ts
mutate((key) => Array.isArray(key) && key[0] === '/appointments')
```

### Helper module (`frontend/lib/calendarGrid.ts`)

Pure functions, unit-tested in isolation:

- `getWeekRange(date: Date): { start: Date; end: Date }` — Monday 00:00 to Sunday 24:00 of the week containing `date`.
- `toGridItem(item: Appointment | CalendarEntry): GridItem` — normalizes both kinds to:
  ```ts
  {
    id: string;
    kind: 'appointment' | 'event';
    title: string;
    day: string;                       // YYYY-MM-DD
    startMinutes: number | null;       // minutes from midnight on `day`
    endMinutes: number | null;         // null → end of day
    raw: Appointment | CalendarEntry;
  }
  ```
- `layoutDayColumn(items: GridItem[]): LaidOut[]` — side-by-side overlap layout. Groups items whose `[startMinutes, endMinutes)` intervals touch; within each group assigns `column` (0-indexed) and `columnCount`. The renderer computes `width = 100% / columnCount` and `left = column * width`. All-day items (both minutes null) are excluded — they go to the all-day pill row.

---

## Section 3: Frontend — week-view layout and components

### New component tree

```
frontend/components/calendar/
  WeekView.tsx              — page body; owns scroll container
  WeekHeader.tsx            — month/year + ‹ › arrows + Today button
  WeekdayStrip.tsx          — 7 cells with weekday code + day-of-month
  HourGutter.tsx            — left column showing 00..23
  DayColumn.tsx             — all-day pill row + hour slots + positioned blocks
  EventBlock.tsx            — one rendered block (appointment or event)
  NowLine.tsx               — current-time horizontal line
  appointmentModal/
    AppointmentModal.tsx    — portal shell with tab switcher
    MakeAppointmentTab.tsx
    RecommendTab.tsx
```

`frontend/app/calendar/page.tsx` shrinks to a thin wrapper that fetches both data sources, owns `currentWeekStart` and `modal` state, and renders `<WeekView>` plus `<AppointmentModal>` when open.

### Layout

The header and weekday strip stay fixed at the top of the calendar area. The hour-grid region scrolls vertically inside the calendar (not the page). Horizontal scroll only appears when the viewport is too narrow to fit 7 columns plus the gutter.

```
┌──────────────────────────────────────────────────────────────┐
│ WeekHeader                                                   │
├──────────────────────────────────────────────────────────────┤
│ WeekdayStrip                                                 │
├──────┬───────────────────────────────────────────────────────┤
│      │ All-day pill row (height: auto)                       │
│ gutt ├────┬────┬────┬────┬────┬────┬────────────────────────┤
│  er  │ Mo │ Di │ Mi │ Do │ Fr │ Sa │ So                      │
│ 00   │    │    │    │    │    │    │                        │
│ 01   │    │    │    │    │    │    │                        │
│ ...  │    │    │    │    │    │    │                        │
│ 23   │    │    │    │    │    │    │                        │
└──────┴────┴────┴────┴────┴────┴────┴────────────────────────┘
```

### Dimensions

- Hour row: **48px**. Whole grid is `24 * 48 = 1152px` tall.
- Default scroll position on first render: **07:00**.
- Gutter width: ~48px, labels right-aligned in muted text.

### Day column internals

- `position: relative`.
- Background paints the hour rows via `repeating-linear-gradient` (1px line at every 48px) in `border` color.
- Right edge: 1px border in `border` color (vertical separators between days).
- Absolutely-positioned `EventBlock` children: `top = startMinutes * (48/60)`, `height = (endMinutes - startMinutes) * (48/60)`. `left` and `width` come from `layoutDayColumn`.

### WeekHeader

- Centered title: `"{Month} {Year}"`; if the week spans two months, `"{Mon1} – {Mon2} {Year}"`.
- `‹` and `›` arrows on either side; each steps one week.
- A `Today` button that jumps to the week containing today.

### WeekdayStrip

- Seven cells using German short codes: `Mo`, `Di`, `Mi`, `Do`, `Fr`, `Sa`, `So`.
- Day-of-month underneath.
- Today: `accent-gold` filled circle around the day number, white number inside.
- Weekend cells (Sa/So): subtle `bg-bg-surface` background tint.

### EventBlock

- Rounded rectangle, 3px left border indicating kind:
  - `accent-gold` → saved feed event.
  - `text-secondary` → custom appointment.
- Title in bold, truncated to one line.
- Below: time range (e.g. `09:00 – 16:30`) in muted text.
- All-day pills render in the all-day row (single line, no time range shown).

### NowLine

- Rendered inside today's `DayColumn` only.
- Position: `currentMinutes * (48/60)`.
- 1px horizontal line in `accent-gold`, 6px filled circle on the left edge.
- `useEffect` with `setInterval(60000)` recomputes position every minute.

### Click behavior

- **Empty area of a day column** → `AppointmentModal` opens in `mode='create'`, tab "Make". `initial.day` = the clicked day; `initial.start_at` snapped to the nearest 30-minute boundary of clicked Y; `initial.end_at` = `start_at + 1h`.
- **Empty area of all-day pill row** → modal opens in `mode='create'`, tab "Make", `initial.day` set, both times `null`.
- **Existing custom appointment block** → modal opens in `mode='edit'`, tab "Make", all fields pre-filled, Delete button shown.
- **Existing saved-event block** → existing `EventDetailOverlay` opens via `openOverlay(eventId)`.

---

## Section 4: Appointment modal

Rendered via `createPortal` like `EventDetailOverlay`. Backdrop click and Escape close it.

### Props

```ts
interface Props {
  mode: 'create' | 'edit'
  initial: {
    id?: string                     // present only in edit mode
    day: string                     // YYYY-MM-DD
    title?: string
    start_at?: string | null
    end_at?: string | null
  }
  onClose: () => void
  onSaved: () => void               // triggers SWR revalidation upstream
}
```

### Tab switcher

Two pill buttons at the top: "Make an appointment" / "Recommend me something". Active tab in `accent-gold`. Switching does not discard input in the other tab; each tab's state lives in modal-local React state until close. In `mode='edit'` the Recommend tab is hidden.

### Tab (a): Make an appointment

Form fields:

- **Title** — text input, required, autofocused on open in create mode.
- **All day** — checkbox. When checked, time pickers hide; `start_at` and `end_at` will be sent as `null`.
- **Start time** — `<input type="time">`, step 15 min. Default in create mode: snapped to clicked Y; in modal-opened-from-pill-row: empty (the All-day checkbox is then checked by default).
- **End time** — same control. Leaving it empty sends `end_at: null`. Hint underneath: *"Leave empty to last until end of day."*
- **Day** — read-only display of `initial.day`.

Footer:

- **Save** (right) — always shown. Calls `createAppointment` or `updateAppointment`, then `onSaved()` and closes.
- **Delete** (left) — only in `mode='edit'`. `window.confirm(...)` prompt, then `deleteAppointment(id)`, then `onSaved()` and closes.
- Cancel is implicit via Esc / backdrop click.

Validation (blocks Save):

- Title non-empty.
- If both times set: `end_at > start_at` on the same calendar day (cross-midnight authoring is **out of scope** for v1 form; backend schema allows it).
- "Only `end_at` set" impossible — UI disables End picker until Start is set.

On API error: Save stays enabled, inline red message under the footer, input values preserved.

### Tab (b): Recommend me something

Layout, top to bottom:

- Same Start / End / All-day controls as tab (a), pre-filled the same way. v1 sends them as context only.
- Chat area styled like `EventChat`.
- Chat input with placeholder `"Tell your assistant what you are searching for..."`.

Placeholder visibility logic — shown when **all three** conditions hold:

1. Input is empty.
2. Input does not have focus.
3. No messages have been sent in the current modal session.

Once any message has been sent in this modal session, the placeholder never returns until the modal is reopened.

Submitting any message calls `recommendAppointment({ day, start_at, end_at, message })`. The hook appends the user bubble, then appends an assistant bubble with the response's `message` ("Currently not implemented"). Single round trip, no streaming. Chat history is **per-modal-session only** — closing the modal drops it.

No Save button on this tab.

---

## Section 5: State management & cache invalidation

`frontend/app/calendar/page.tsx` owns:

- `currentWeekStart: Date` — Monday 00:00 of the visible week.
- `modal: { mode, initial } | null` — open state for `AppointmentModal`.

SWR keys feeding the grid:

- `['/appointments', weekStartISO, weekEndISO]` — custom appointments for visible week.
- `/calendar` — existing; filtered client-side to visible week.

`AppShell.fanOutEventCaches` adds:

```ts
mutate((key) => Array.isArray(key) && key[0] === '/appointments')
```

`AppointmentModal.onSaved` triggers parent revalidation for both `/appointments` ranges currently cached and `/calendar`.

**No optimistic UI for appointments** — modal stays open until the API confirms, then closes. Optimistic UI for save/unsave of feed events continues to work as it does today.

---

## Section 6: Error handling & edge cases

- **`GET /appointments` fails** → inline error banner above the grid (*"Couldn't load appointments. Retry"*); saved events still render.
- **`GET /calendar` fails** → separate banner; appointments still render.
- **Create / update / delete fails** → modal stays open with inline red message; input values preserved.
- **Empty week** → grid still renders. Faint hint at the bottom: *"Click anywhere to add an appointment."*
- **DST shifts** — backend stores timezone-aware UTC; frontend uses local-time projection via `Date#getHours()` etc., which correctly handles DST because the absolute UTC instant is unchanged. Seed script constructs local Hamburg times and converts to UTC, not the reverse.
- **Recommend tab** — placeholder backend returns 200 with `"Currently not implemented"`. On unexpected error, chat surfaces a generic `"Couldn't reach assistant"` bubble; modal-session-only history rule still applies.
- **Concurrent edits** — if an open appointment gets deleted in another tab, Save returns 404; modal shows *"Appointment no longer exists"* and closes after acknowledgement.

---

## Section 7: Testing

### Backend

- `tests/db/test_appointment.py` — model insert; index hit smoke check.
- `tests/api/test_appointments.py` — happy path for each route; window filter; rejection of `(null start, set end)`; rejection of `end ≤ start` on same day; auth scope (current user only sees own).
- `tests/scripts/test_seed_default_appointments.py` — idempotent run inserts the right count (45 weekdays in Jun + Jul 2026); re-running inserts zero.

### Frontend

- Unit tests for `lib/calendarGrid.ts`:
  - `getWeekRange` boundaries (Monday start, DST week).
  - `toGridItem` normalization for both kinds, including events with null `end_datetime`.
  - `layoutDayColumn` overlap math: two overlapping → both at 50% width; three pairwise overlaps → all at 33%; non-overlapping → 100% width; all-day items excluded.
- Component tests (matching repo's existing pattern):
  - `WeekView` renders today highlight; `NowLine` appears only in today's column.
  - Clicking empty grid cell opens modal with correct `day` and snapped `start_at`.
  - Clicking custom appointment block opens modal in edit mode with Delete present.
  - Clicking saved-event block opens `EventDetailOverlay`.
  - Recommend tab placeholder visibility across focus, blur, empty, and post-send states.

---

## Section 8: Out of scope

- Day view, agenda view, month view (week-only for v1).
- Drag-to-create, drag-to-resize, drag-to-move.
- Cross-midnight appointment authoring via the form (backend schema supports it).
- Recurring appointments (Turing seed creates each weekday as a separate row).
- Real recommender logic for tab (b).
- Multi-day events spanning more than one column.
- Calendar export (iCal, Google).
- Sharing / collaborator visibility.
