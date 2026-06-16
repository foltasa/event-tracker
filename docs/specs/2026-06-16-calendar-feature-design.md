# Calendar Feature Design

**Date:** 2026-06-16  
**Branch:** fix/digest-followup  
**Status:** Approved

---

## Overview

Three connected pieces:

1. **Fix broken save button** — API URL mismatch between frontend and backend, plus missing SWR cache invalidation after save.
2. **Calendar page** — New `/calendar` page with a side-by-side mini calendar + event list layout.
3. **Chat inline event chips** — Parse `[event:ID]` markers in agent messages and render interactive chips with a Save button.

No backend schema changes required. The backend calendar CRUD (`GET /calendar`, `POST /calendar`, `DELETE /calendar/{event_id}`) and all relevant types are already fully implemented.

---

## Section 1: Bug Fix + Data Layer

### Save URL mismatch

`frontend/lib/api.ts:saveToCalendar` currently calls:
```
POST /calendar/{eventId}   (no body)
```
The backend route expects:
```
POST /calendar   body: { event_id: string }
```
Fix: change the `jsonFetch` call to hit `/calendar` with a JSON body `{ event_id: eventId }`.

### Save state not reflected after saving

After `saveToCalendar` resolves, the `EventDetailOverlay` still shows "Save to Calendar" because nothing refetches the event. Fix: after the call resolves, call `mutate(\`/events/${eventId}\`)` via SWR to trigger a refetch of `EventWithContext`, which carries `is_saved: true`.

This applies wherever `handleSave` is wired up (dashboard `page.tsx`).

---

## Section 2: Calendar Page

**File:** `frontend/app/calendar/page.tsx`

The `/calendar` nav link already exists in `TopNav`. The page needs to be created.

### Layout

Two-column body below the standard `TopNav`:

- **Left column** — mini calendar grid
- **Right column** — saved event list

### Left column: Mini calendar grid

- Shows one month at a time; prev/next arrow buttons to navigate months.
- Rendered from `CalendarResponse` data — no external library needed (7-column CSS grid).
- Days with at least one saved event show a gold dot beneath the date number.
- Clicking a day sets `selectedDate` state, filtering the right panel to events on that day.
- Clicking the selected day again deselects it (shows all events in that month).
- Defaults to current month; if the current month has no saved events and at least one saved event exists, jumps to the earliest future month that has one. If no saved events exist at all, stays on the current month and shows the empty state in the right column.

### Right column: Event list

- Fetches `GET /calendar` via SWR on mount.
- Displays all saved events in ascending `start_datetime` order, filtered to the selected day when one is active.
- Each row shows: category badge · title · date/time · venue · **×** remove button.
- Clicking the **×** calls `DELETE /calendar/{eventId}`, then optimistically removes the entry from the SWR cache (reverts on failure).
- Clicking anywhere else on the row opens `EventDetailOverlay` (same component as the dashboard). Justification is passed as `null` (digest justifications are dashboard-only).
- Empty state: short message + "Browse events →" link back to `/`.

---

## Section 3: Chat Inline Event Chips

### New component: `EventChip` (`frontend/components/EventChip.tsx`)

Props: `{ eventId: string; onSave: (id: string) => void }`

Behaviour:
- Fetches `/events/{eventId}` via SWR. Will be a cache hit if the event was previously viewed.
- Loading state: skeleton placeholder matching chip dimensions.
- Renders: `[category badge] [title] · [date] · [venue]` + **Save / Saved ✓** button on the right.
- Save button calls `onSave(eventId)` then mutates the SWR key — button flips to "Saved ✓" optimistically.
- On fetch error or 404: renders a plain text fallback `[event not found]` without crashing.

### Message parsing helper

**Function:** `parseMessageContent(text: string): Array<{ type: 'text'; value: string } | { type: 'event'; id: string }>`

- Regex: `/\[event:([a-f0-9-]{36})\]/g` (UUID format)
- Returns interleaved text and event segments.
- If no `[event:ID]` markers present, returns a single `{ type: 'text' }` segment — zero change to existing rendering.
- Malformed markers (non-UUID content) fall through to plain text.

### Integration points

Both `ChatPanel.tsx` and the `EventChat` component inside `EventDetailOverlay.tsx` render assistant message bubbles. Both need the parsing applied to assistant messages. The `parseMessageContent` helper and the `EventChip` component are shared between them.

---

## Section 4: Error Handling & Edge Cases

### Save actions (all surfaces)

- **Optimistic UI:** button flips to "Saved ✓" immediately; reverts with an inline `Failed to save — try again` message on API error.
- **Idempotency:** backend `POST /calendar` is already idempotent on `(user, event)` — double-clicks are safe.

### Calendar page

- **SWR error:** shows `Failed to load calendar` with a retry button.
- **Remove action:** optimistic removal from local SWR cache; reverts on failure.
- **Overlay from calendar:** `justification` prop is always `null`.

### EventChip

- 404 / network error → plain text fallback `[event not found]`.
- Malformed `[event:abc]` (not a valid UUID) → regex doesn't match → plain text.

---

## Out of Scope

- Fixing existing dashboard EventDetailOverlay bugs (event detail not loading correctly on click from feed/digest).
- Unsave action from inside the EventDetailOverlay (only available via the calendar page remove button).
- External calendar export (iCal, Google Calendar).
