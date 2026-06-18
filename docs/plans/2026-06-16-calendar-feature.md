# Calendar Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the save-to-calendar flow end-to-end, add a `/calendar` page with a month grid, and render inline event chips with Save buttons inside chat messages.

**Architecture:** Fix the existing API URL mismatch in `api.ts` and add SWR revalidation after saves. Add a `parseMessageContent` helper that splits agent text on `[event:UUID]` markers, then render each marker as a self-contained `EventChip` component (SWR fetch + optimistic Save). Build the calendar page as a single-column month grid that opens the existing `EventDetailOverlay` on day click.

**Tech Stack:** Next.js 14 App Router, SWR, Vitest + React Testing Library, Tailwind CSS, existing backend calendar CRUD (no backend changes).

**Spec:** `docs/specs/2026-06-16-calendar-feature-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `frontend/lib/api.ts` | Fix `saveToCalendar` URL |
| Modify | `frontend/app/page.tsx` | SWR mutate after save |
| Create | `frontend/lib/parseMessageContent.ts` | Parse `[event:UUID]` from text |
| Create | `frontend/lib/__tests__/parseMessageContent.test.ts` | Unit tests for parser |
| Create | `frontend/components/EventChip.tsx` | Inline event chip with Save button |
| Create | `frontend/components/__tests__/EventChip.test.tsx` | Component tests for EventChip |
| Modify | `frontend/components/ChatPanel.tsx` | Use parseMessageContent + EventChip |
| Modify | `frontend/components/EventDetailOverlay.tsx` | Same for EventChat |
| Create | `frontend/app/calendar/page.tsx` | Calendar month grid page |

---

## Task 1: Fix saveToCalendar URL bug

**Files:**
- Modify: `frontend/lib/api.ts` (~line 119)
- Create: `frontend/lib/__tests__/api.test.ts`

The frontend calls `POST /calendar/{eventId}` but the backend expects `POST /calendar` with body `{ event_id: string }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/api.test.ts`:

```ts
import { saveToCalendar } from '@/lib/api'

const mockEntry = {
  id: 'sav-1',
  event: { id: 'evt-1', title: 'Test', summary: null, start_datetime: '2026-06-20T18:00:00Z',
    end_datetime: null, venue_name: null, venue_address: null, category: 'music' as const,
    tags: [], price_min: null, price_max: null, is_free: true, currency: 'EUR',
    image_url: null, source_url: 'https://example.com', source: 'test', is_active: true },
  saved_at: '2026-06-16T10:00:00Z',
}

describe('saveToCalendar', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockEntry,
    } as Response)
  })

  it('POSTs to /calendar (not /calendar/{id})', async () => {
    await saveToCalendar('evt-1')
    const [url] = vi.mocked(global.fetch).mock.calls[0]
    expect(url).toMatch(/\/calendar$/)
  })

  it('sends event_id in the request body', async () => {
    await saveToCalendar('evt-1')
    const [, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(JSON.parse(init!.body as string)).toEqual({ event_id: 'evt-1' })
  })
})
```

- [ ] **Step 2: Run the test and confirm it fails**

```
cd frontend && npx vitest run lib/__tests__/api.test.ts
```

Expected: FAIL — the URL assertion fails because current code uses `/calendar/evt-1`.

- [ ] **Step 3: Fix the URL in api.ts**

In `frontend/lib/api.ts`, replace the `saveToCalendar` return statement:

```ts
// Before:
return jsonFetch<CalendarEntry>(`/calendar/${encodeURIComponent(eventId)}`, { method: "POST" });

// After:
return jsonFetch<CalendarEntry>('/calendar', { method: 'POST', body: JSON.stringify({ event_id: eventId }) });
```

- [ ] **Step 4: Run tests and confirm they pass**

```
cd frontend && npx vitest run lib/__tests__/api.test.ts
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```
git add frontend/lib/api.ts frontend/lib/__tests__/api.test.ts
git commit -m "fix: correct saveToCalendar URL and body to match backend POST /calendar"
```

---

## Task 2: Refresh is_saved state after save

**Files:**
- Modify: `frontend/app/page.tsx`

After a save, the `EventDetailOverlay` still shows "Save to Calendar" because the SWR cache entry for the event is stale. Add a global `mutate` call after save to revalidate it.

- [ ] **Step 1: Add useSWRConfig import and mutate call**

In `frontend/app/page.tsx`, apply this diff:

```ts
// Add to imports at top:
import useSWR, { useSWRConfig } from 'swr'

// Inside DashboardPage(), add after the useState lines:
const { mutate } = useSWRConfig()

// Replace handleSave:
const handleSave = useCallback(async (eventId: string) => {
  await saveToCalendar(eventId)
  mutate(`/events/${eventId}`)
}, [mutate])
```

The full updated `DashboardPage` component top section looks like:

```tsx
export default function DashboardPage() {
  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS)
  const { mutate } = useSWRConfig()

  const { data: digest } = useSWR('/digest', getDigest)

  const handleFeedback = useCallback(async (eventId: string, sentiment: Sentiment) => {
    await postFeedback({ event_id: eventId, sentiment, comment: null })
  }, [])

  const handleSave = useCallback(async (eventId: string) => {
    await saveToCalendar(eventId)
    mutate(`/events/${eventId}`)
  }, [mutate])

  const handleCardClick = useCallback((eventId: string) => {
    setActiveEventId(eventId)
  }, [])
  // ... rest unchanged
```

- [ ] **Step 2: Verify no type errors**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/app/page.tsx
git commit -m "fix: revalidate event SWR cache after save so is_saved flips to true"
```

---

## Task 3: parseMessageContent helper

**Files:**
- Create: `frontend/lib/parseMessageContent.ts`
- Create: `frontend/lib/__tests__/parseMessageContent.test.ts`

Pure function that splits a string on `[event:UUID]` markers.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/__tests__/parseMessageContent.test.ts`:

```ts
import { parseMessageContent } from '@/lib/parseMessageContent'

const UUID = '550e8400-e29b-41d4-a716-446655440000'

describe('parseMessageContent', () => {
  it('returns a single text segment when no markers present', () => {
    const result = parseMessageContent('Hello world')
    expect(result).toEqual([{ type: 'text', value: 'Hello world' }])
  })

  it('returns a single text segment for empty string', () => {
    expect(parseMessageContent('')).toEqual([{ type: 'text', value: '' }])
  })

  it('parses a single event marker into an event segment', () => {
    const result = parseMessageContent(`[event:${UUID}]`)
    expect(result).toEqual([{ type: 'event', id: UUID }])
  })

  it('splits text around a marker correctly', () => {
    const result = parseMessageContent(`Check out [event:${UUID}] tonight!`)
    expect(result).toEqual([
      { type: 'text', value: 'Check out ' },
      { type: 'event', id: UUID },
      { type: 'text', value: ' tonight!' },
    ])
  })

  it('handles multiple markers', () => {
    const UUID2 = '660e8400-e29b-41d4-a716-446655440001'
    const result = parseMessageContent(`A [event:${UUID}] and B [event:${UUID2}]`)
    expect(result).toEqual([
      { type: 'text', value: 'A ' },
      { type: 'event', id: UUID },
      { type: 'text', value: ' and B ' },
      { type: 'event', id: UUID2 },
    ])
  })

  it('does not match malformed markers with non-UUID content', () => {
    const result = parseMessageContent('[event:not-a-uuid]')
    expect(result).toEqual([{ type: 'text', value: '[event:not-a-uuid]' }])
  })

  it('is case-insensitive for hex digits in UUID', () => {
    const upperUUID = UUID.toUpperCase()
    const result = parseMessageContent(`[event:${upperUUID}]`)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('event')
  })
})
```

- [ ] **Step 2: Run tests and confirm they fail**

```
cd frontend && npx vitest run lib/__tests__/parseMessageContent.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement parseMessageContent**

Create `frontend/lib/parseMessageContent.ts`:

```ts
export type MessageSegment =
  | { type: 'text'; value: string }
  | { type: 'event'; id: string }

const EVENT_RE = /\[event:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]/gi

export function parseMessageContent(text: string): MessageSegment[] {
  const segments: MessageSegment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  EVENT_RE.lastIndex = 0
  while ((match = EVENT_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'event', id: match[1] })
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) })
  }

  return segments.length > 0 ? segments : [{ type: 'text', value: text }]
}
```

- [ ] **Step 4: Run tests and confirm they pass**

```
cd frontend && npx vitest run lib/__tests__/parseMessageContent.test.ts
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```
git add frontend/lib/parseMessageContent.ts frontend/lib/__tests__/parseMessageContent.test.ts
git commit -m "feat: add parseMessageContent helper for [event:UUID] markers"
```

---

## Task 4: EventChip component

**Files:**
- Create: `frontend/components/EventChip.tsx`
- Create: `frontend/components/__tests__/EventChip.test.tsx`

Inline chip that fetches event details via SWR and renders a Save button.

- [ ] **Step 1: Write the failing tests**

Create `frontend/components/__tests__/EventChip.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import EventChip from '@/components/EventChip'

vi.mock('swr', () => ({
  default: vi.fn(),
  useSWRConfig: () => ({ mutate: vi.fn() }),
}))
vi.mock('@/lib/api', () => ({
  getEventDetail: vi.fn(),
  saveToCalendar: vi.fn(),
}))

import useSWR from 'swr'
import { saveToCalendar } from '@/lib/api'

const mockEvent = {
  id: 'evt-1', title: 'Tango Festival', summary: null,
  start_datetime: '2026-06-20T18:00:00Z', end_datetime: null,
  venue_name: 'Fabrik', venue_address: null, category: 'music' as const,
  tags: [], price_min: null, price_max: null, is_free: false, currency: 'EUR',
  image_url: null, source_url: 'https://example.com', source: 'test',
  is_active: true, user_sentiment: null, user_comment: null, is_saved: false,
}

describe('EventChip', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders a loading skeleton when event data is not yet available', () => {
    vi.mocked(useSWR).mockReturnValue({ data: undefined, error: undefined, mutate: vi.fn() } as any)
    const { container } = render(<EventChip eventId="evt-1" />)
    expect(container.querySelector('[data-testid="chip-skeleton"]')).toBeInTheDocument()
  })

  it('renders fallback text when fetch errors', () => {
    vi.mocked(useSWR).mockReturnValue({ data: undefined, error: new Error('404'), mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByText('[event not found]')).toBeInTheDocument()
  })

  it('renders event title and venue when loaded', () => {
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByText('Tango Festival')).toBeInTheDocument()
    expect(screen.getByText(/Fabrik/)).toBeInTheDocument()
  })

  it('shows Save button when is_saved is false', () => {
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument()
    expect(screen.queryByText(/saved ✓/i)).not.toBeInTheDocument()
  })

  it('shows Saved ✓ when is_saved is true', () => {
    vi.mocked(useSWR).mockReturnValue({ data: { ...mockEvent, is_saved: true }, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /saved/i })).toBeInTheDocument()
  })

  it('calls saveToCalendar with the event id on Save click', async () => {
    const mutate = vi.fn()
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate } as any)
    vi.mocked(saveToCalendar).mockResolvedValue({} as any)
    render(<EventChip eventId="evt-1" />)
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(saveToCalendar).toHaveBeenCalledWith('evt-1'))
  })
})
```

- [ ] **Step 2: Run tests and confirm they fail**

```
cd frontend && npx vitest run components/__tests__/EventChip.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement EventChip**

Create `frontend/components/EventChip.tsx`:

```tsx
'use client'
import useSWR from 'swr'
import { useState } from 'react'
import { getEventDetail, saveToCalendar } from '@/lib/api'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'short', day: 'numeric', month: 'short',
  })
}

export default function EventChip({ eventId }: { eventId: string }) {
  const { data: event, error, mutate } = useSWR(
    `/events/${eventId}`,
    () => getEventDetail(eventId),
  )
  const [saveError, setSaveError] = useState<string | null>(null)

  if (error) return <span className="text-[9px] text-text-muted">[event not found]</span>
  if (!event) {
    return (
      <span
        data-testid="chip-skeleton"
        className="inline-block h-5 w-48 rounded bg-bg-surface animate-pulse"
      />
    )
  }

  async function handleSave() {
    if (!event) return
    setSaveError(null)
    mutate({ ...event, is_saved: true }, false)
    try {
      await saveToCalendar(eventId)
      mutate()
    } catch {
      mutate({ ...event, is_saved: false }, false)
      setSaveError('Failed to save — try again')
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap my-0.5">
      <span className="inline-flex items-center gap-1.5 bg-accent-gold-light border border-accent-gold/30 rounded px-2 py-1 text-[9px] text-text-primary">
        <span className="uppercase tracking-wider font-semibold text-accent-gold">{event.category}</span>
        <span className="font-semibold">{event.title}</span>
        <span className="text-text-muted">·</span>
        <span className="text-text-muted">{formatDate(event.start_datetime)}</span>
        {event.venue_name && (
          <>
            <span className="text-text-muted">·</span>
            <span className="text-text-muted">{event.venue_name}</span>
          </>
        )}
        <button
          onClick={handleSave}
          disabled={event.is_saved}
          className="ml-1 rounded bg-accent-gold text-bg-page px-2 py-0.5 text-[8px] font-semibold disabled:opacity-70"
        >
          {event.is_saved ? 'Saved ✓' : 'Save'}
        </button>
      </span>
      {saveError && <span className="text-[8px] text-red-500">{saveError}</span>}
    </span>
  )
}
```

- [ ] **Step 4: Run tests and confirm they pass**

```
cd frontend && npx vitest run components/__tests__/EventChip.test.tsx
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```
git add frontend/components/EventChip.tsx frontend/components/__tests__/EventChip.test.tsx
git commit -m "feat: add EventChip component with optimistic save button"
```

---

## Task 5: Wire EventChip into ChatPanel

**Files:**
- Modify: `frontend/components/ChatPanel.tsx`

Replace plain text rendering of assistant messages with segment-aware rendering.

- [ ] **Step 1: Update ChatPanel.tsx**

Add imports at the top of `frontend/components/ChatPanel.tsx`:

```tsx
import { parseMessageContent } from '@/lib/parseMessageContent'
import EventChip from '@/components/EventChip'
```

Replace the assistant message bubble (the `<div>` inside `Fragment` that currently renders `{msg.content}`) with:

```tsx
<Fragment key={msg.id}>
  {showIndicator && (
    <div className="flex items-center gap-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
      <span className="text-[9px] italic text-accent-gold">{indicatorText}</span>
    </div>
  )}
  <div className="self-start max-w-[92%] rounded-lg rounded-bl-sm border border-border bg-white px-2.5 py-1.5 text-[10px] text-text-primary">
    <p className="leading-relaxed whitespace-pre-wrap">
      {parseMessageContent(msg.content).map((seg, si) =>
        seg.type === 'event'
          ? <EventChip key={`${msg.id}-ev-${si}`} eventId={seg.id} />
          : <span key={`${msg.id}-tx-${si}`}>{seg.value}</span>
      )}
    </p>
    {msg.isStreaming && msg.content !== '' && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
    {msg.tokenUsage && (
      <p className="text-[8px] text-text-muted mt-1 text-right">
        {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
      </p>
    )}
  </div>
</Fragment>
```

The `onCardClick`, `onFeedback`, `onSave` props on `ChatPanel` are still accepted (they're wired from the parent page) but the chip handles its own save internally. No prop changes needed.

- [ ] **Step 2: Type-check**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run all frontend tests**

```
cd frontend && npm test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```
git add frontend/components/ChatPanel.tsx
git commit -m "feat: render [event:ID] markers as EventChip in ChatPanel"
```

---

## Task 6: Wire EventChip into EventChat (EventDetailOverlay)

**Files:**
- Modify: `frontend/components/EventDetailOverlay.tsx`

Same change as Task 5, applied to the `EventChat` component inside the overlay.

- [ ] **Step 1: Update EventDetailOverlay.tsx**

Add imports at the top of `frontend/components/EventDetailOverlay.tsx`:

```tsx
import { parseMessageContent } from '@/lib/parseMessageContent'
import EventChip from '@/components/EventChip'
```

Inside `EventChat`, replace the assistant message bubble (the `<div>` inside `Fragment` that currently renders `{msg.content}`) with:

```tsx
<Fragment key={msg.id}>
  {showIndicator && (
    <div className="flex items-center gap-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
      <span className="text-[9px] italic text-accent-gold">{indicatorText}</span>
    </div>
  )}
  <div className="self-start max-w-[90%] rounded-lg rounded-bl-sm border border-border bg-white px-3 py-1.5 text-[10px] text-text-primary leading-relaxed">
    {parseMessageContent(msg.content).map((seg, si) =>
      seg.type === 'event'
        ? <EventChip key={`${msg.id}-ev-${si}`} eventId={seg.id} />
        : <span key={`${msg.id}-tx-${si}`}>{seg.value}</span>
    )}
    {msg.isStreaming && msg.content !== '' && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
    {msg.tokenUsage && (
      <p className="text-[8px] text-text-muted mt-1 text-right">
        {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
      </p>
    )}
  </div>
</Fragment>
```

- [ ] **Step 2: Type-check and run all tests**

```
cd frontend && npx tsc --noEmit && npm test
```

Expected: no errors, all tests pass.

- [ ] **Step 3: Commit**

```
git add frontend/components/EventDetailOverlay.tsx
git commit -m "feat: render [event:ID] markers as EventChip in EventDetailOverlay chat"
```

---

## Task 7: Calendar page

**Files:**
- Create: `frontend/app/calendar/page.tsx`

Single-column month grid. Fetches `GET /calendar`, shows gold dots on days with saved events, opens `EventDetailOverlay` on day click.

- [ ] **Step 1: Create the calendar page**

Create `frontend/app/calendar/page.tsx`:

```tsx
'use client'
import { useState, useEffect, useRef } from 'react'
import useSWR from 'swr'
import Link from 'next/link'
import { getCalendar, getEventDetail } from '@/lib/api'
import type { CalendarEntry, CalendarResponse, Sentiment } from '@/lib/types'
import TopNav from '@/components/TopNav'
import EventDetailOverlay from '@/components/EventDetailOverlay'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']

function toDateKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function groupByDate(entries: CalendarEntry[]): Map<string, CalendarEntry[]> {
  const map = new Map<string, CalendarEntry[]>()
  for (const entry of entries) {
    const key = toDateKey(entry.event.start_datetime)
    const list = map.get(key) ?? []
    list.push(entry)
    map.set(key, list)
  }
  return map
}

function CalendarGrid({
  year, month, byDate, todayKey, onDayClick,
}: {
  year: number
  month: number
  byDate: Map<string, CalendarEntry[]>
  todayKey: string
  onDayClick: (eventId: string) => void
}) {
  const firstDayOfWeek = (new Date(year, month, 1).getDay() + 6) % 7 // Mon=0
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (number | null)[] = [
    ...Array<null>(firstDayOfWeek).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]

  return (
    <div className="grid grid-cols-7 gap-1">
      {DAYS.map((d) => (
        <div key={d} className="text-center text-[9px] text-text-muted py-1 uppercase tracking-wider">{d}</div>
      ))}
      {cells.map((day, i) => {
        if (day === null) return <div key={`pad-${i}`} />
        const dateKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
        const entries = byDate.get(dateKey)
        const hasEvents = !!entries
        const isToday = dateKey === todayKey
        return (
          <div
            key={day}
            data-testid={`day-${day}`}
            onClick={() => hasEvents && onDayClick(entries![0].event.id)}
            className={[
              'flex flex-col items-center py-2 rounded',
              hasEvents ? 'cursor-pointer hover:bg-accent-gold-light' : 'cursor-default',
              isToday ? 'ring-1 ring-accent-gold' : '',
            ].join(' ')}
          >
            <span className={`text-xs leading-none ${isToday ? 'font-bold text-accent-gold' : 'text-text-primary'}`}>
              {day}
            </span>
            {hasEvents
              ? <span className="w-1.5 h-1.5 rounded-full bg-accent-gold mt-1" />
              : <span className="w-1.5 h-1.5 mt-1" />
            }
          </div>
        )
      })}
    </div>
  )
}

function EventDetailOverlayLoader({
  eventId, onClose,
}: {
  eventId: string
  onClose: () => void
}) {
  const { data: event } = useSWR(`/events/${eventId}`, () => getEventDetail(eventId))
  if (!event) return null
  return (
    <EventDetailOverlay
      event={event}
      justification={null}
      onClose={onClose}
      onFeedback={() => {}}
      onSave={() => {}}
    />
  )
}

export default function CalendarPage() {
  const today = new Date()
  const todayKey = toDateKey(today.toISOString())
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const hasAutoJumped = useRef(false)

  const { data, error, isLoading } = useSWR<CalendarResponse>('/calendar', getCalendar)
  const entries = data?.entries ?? []
  const byDate = groupByDate(entries)

  // Auto-jump to earliest month with events on first load
  useEffect(() => {
    if (hasAutoJumped.current || !data || data.entries.length === 0) return
    const currentMonthHasEvents = data.entries.some((e) => {
      const d = new Date(e.event.start_datetime)
      return d.getFullYear() === year && d.getMonth() === month
    })
    if (!currentMonthHasEvents) {
      const earliest = data.entries.reduce<Date>((min, e) => {
        const d = new Date(e.event.start_datetime)
        return d < min ? d : min
      }, new Date(data.entries[0].event.start_datetime))
      setYear(earliest.getFullYear())
      setMonth(earliest.getMonth())
    }
    hasAutoJumped.current = true
  }, [data])

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11) }
    else setMonth(m => m - 1)
  }

  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0) }
    else setMonth(m => m + 1)
  }

  const currentMonthEntries = entries.filter((e) => {
    const d = new Date(e.event.start_datetime)
    return d.getFullYear() === year && d.getMonth() === month
  })

  const dateLabel = today.toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg-page">
      <TopNav active="calendar" date={`Hamburg · ${dateLabel}`} />

      <main className="flex-1 overflow-y-auto flex flex-col items-center py-8 px-4">
        <div className="w-full max-w-sm">
          {/* Month navigation */}
          <div className="flex items-center justify-between mb-6">
            <button
              onClick={prevMonth}
              aria-label="Previous month"
              className="rounded px-2 py-1 text-text-secondary hover:text-text-primary"
            >
              ‹
            </button>
            <h2 className="font-serif font-bold text-base text-text-primary">
              {MONTHS[month]} {year}
            </h2>
            <button
              onClick={nextMonth}
              aria-label="Next month"
              className="rounded px-2 py-1 text-text-secondary hover:text-text-primary"
            >
              ›
            </button>
          </div>

          {/* Calendar grid */}
          {isLoading && (
            <div className="text-center text-xs text-text-muted py-8">Loading…</div>
          )}
          {error && (
            <div className="text-center text-xs text-red-500 py-8">
              Failed to load calendar.{' '}
              <button onClick={() => window.location.reload()} className="underline">Retry</button>
            </div>
          )}
          {!isLoading && !error && (
            <CalendarGrid
              year={year}
              month={month}
              byDate={byDate}
              todayKey={todayKey}
              onDayClick={setActiveEventId}
            />
          )}

          {/* Empty state */}
          {!isLoading && !error && entries.length === 0 && (
            <p className="text-center text-xs text-text-muted mt-8">
              No saved events yet —{' '}
              <Link href="/" className="text-accent-gold underline">browse events to save some →</Link>
            </p>
          )}

          {/* Current month count hint */}
          {!isLoading && !error && entries.length > 0 && currentMonthEntries.length === 0 && (
            <p className="text-center text-[10px] text-text-muted mt-4">
              No saved events this month. Use ‹ › to navigate.
            </p>
          )}
        </div>
      </main>

      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          onClose={() => setActiveEventId(null)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run all tests**

```
cd frontend && npm test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```
git add frontend/app/calendar/page.tsx
git commit -m "feat: add /calendar page with month grid and saved event dots"
```

---

## Task 8: Update spec commit

- [ ] **Step 1: Commit the updated spec**

The spec was already modified to reflect the single-column calendar design. Commit the updated spec:

```
git add docs/specs/2026-06-16-calendar-feature-design.md
git commit -m "docs: update calendar spec to single-column grid layout"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Fix saveToCalendar URL bug → Task 1
- ✅ Fix is_saved state refresh → Task 2
- ✅ parseMessageContent helper → Task 3
- ✅ EventChip component with optimistic save → Task 4
- ✅ EventChip in ChatPanel → Task 5
- ✅ EventChip in EventDetailOverlay EventChat → Task 6
- ✅ Calendar page with month grid → Task 7
- ✅ Gold dots on days with events → Task 7 (CalendarGrid)
- ✅ Today highlighted → Task 7 (CalendarGrid, `ring-1 ring-accent-gold`)
- ✅ Prev/next month navigation → Task 7
- ✅ Auto-jump to earliest month with events → Task 7 (`useEffect` + `hasAutoJumped`)
- ✅ Empty state → Task 7
- ✅ Opens EventDetailOverlay on day click → Task 7 (`EventDetailOverlayLoader`)
- ✅ Justification is null → Task 7 (`justification={null}`)
- ✅ Error state with retry → Task 7
- ✅ EventChip fetch error → plain text fallback → Task 4

**Placeholder scan:** No TBDs, TODOs, or "similar to" references. All steps have complete code. ✓

**Type consistency:**
- `MessageSegment` defined in Task 3 (`parseMessageContent.ts`), consumed in Tasks 5 and 6 — consistent.
- `EventChip` props: `{ eventId: string }` — consistent across Tasks 4, 5, 6, 7.
- `CalendarEntry`, `CalendarResponse` imported from `@/lib/types` — already defined, not redefined.
- `toDateKey` defined inside `calendar/page.tsx` and used by `groupByDate` and `CalendarGrid` in the same file. ✓
- `EventDetailOverlayLoader` in calendar page is a local component (not the one in dashboard's `page.tsx`) — named identically but scoped — no conflict. ✓
