# Timetable Category Colors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Color-code timetable blocks by event category, distinguish recommendations via opacity, and simplify block text (drop "Recommendation:" label, promote time to near-black).

**Architecture:** A single `categoryColors.ts` module in `frontend/lib/` owns the palette. `EventBlock.tsx` and `AllDayStrip.tsx` import from it and apply background via inline `style`. Recommendation state is expressed with `opacity: 0.55`. Appointments stay white so the user's own items remain visually distinct.

**Tech Stack:** Next.js (App Router) + React + TypeScript + Tailwind + Vitest / @testing-library/react.

---

## File Structure

- **Create** `frontend/lib/categoryColors.ts` — palette map + `categoryBg()` helper. One responsibility: category → hex.
- **Create** `frontend/lib/__tests__/categoryColors.test.ts` — unit tests for the helper.
- **Modify** `frontend/components/calendar/EventBlock.tsx` — swap bg/opacity/time logic, remove "Recommendation:" label.
- **Modify** `frontend/components/calendar/AllDayStrip.tsx` — same palette + opacity rules on all-day chips.
- **Modify** `frontend/components/__tests__/EventBlock.test.tsx` — replace the "renders Recommendation: label" assertion, add background + opacity assertions.

Spec reference: `docs/specs/2026-07-12-timetable-category-colors-design.md`.

Working directory for all commands: `frontend/`. Tests via `npm test`. Type-check via `npx tsc --noEmit`.

---

## Task 1: Palette module + unit tests

**Files:**
- Create: `frontend/lib/categoryColors.ts`
- Create: `frontend/lib/__tests__/categoryColors.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/categoryColors.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { CATEGORY_BG, RECOMMENDATION_OPACITY, categoryBg } from '@/lib/categoryColors'

describe('categoryColors', () => {
  it('exports a hex for every EventCategory key', () => {
    const keys = [
      'concerts', 'party', 'comedy', 'theater', 'arts', 'literature',
      'film', 'family', 'food', 'sports', 'outdoor', 'other',
    ] as const
    for (const k of keys) {
      expect(CATEGORY_BG[k]).toMatch(/^#[0-9a-fA-F]{6}$/)
    }
  })

  it('categoryBg returns the matching hex for a known category', () => {
    expect(categoryBg('concerts')).toBe(CATEGORY_BG.concerts)
    expect(categoryBg('party')).toBe(CATEGORY_BG.party)
  })

  it('categoryBg falls back to the "other" swatch for null / undefined', () => {
    expect(categoryBg(null)).toBe(CATEGORY_BG.other)
    expect(categoryBg(undefined)).toBe(CATEGORY_BG.other)
  })

  it('exposes recommendation opacity as 0.55', () => {
    expect(RECOMMENDATION_OPACITY).toBe(0.55)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- lib/__tests__/categoryColors.test.ts`

Expected: FAIL with module-resolution error (`Cannot find module '@/lib/categoryColors'`).

- [ ] **Step 3: Create the palette module**

Create `frontend/lib/categoryColors.ts`:

```ts
import type { EventCategory } from '@/lib/types'

// Soft pastel backgrounds tuned to the warm-cream page (#faf7f2).
// Every value keeps near-black text (#1a1208) readable per the spec at
// docs/specs/2026-07-12-timetable-category-colors-design.md.
export const CATEGORY_BG: Record<EventCategory, string> = {
  concerts:   '#e0d3ea',
  party:      '#f4e2a8',
  comedy:     '#f5cfc6',
  theater:    '#e8ccd0',
  arts:       '#d3e0cf',
  literature: '#eee1c6',
  film:       '#cfd8e3',
  family:     '#b9dcd8',
  food:       '#edc9b3',
  sports:     '#cfe1d5',
  outdoor:    '#dbdfb8',
  other:      '#e0d8ca',
}

// Recommendation slots render the same category background at reduced opacity
// so the beige page bleeds through, replacing the old "Recommendation:" label.
export const RECOMMENDATION_OPACITY = 0.55

export function categoryBg(category: EventCategory | null | undefined): string {
  if (!category) return CATEGORY_BG.other
  return CATEGORY_BG[category] ?? CATEGORY_BG.other
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- lib/__tests__/categoryColors.test.ts`

Expected: PASS (4/4).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/categoryColors.ts frontend/lib/__tests__/categoryColors.test.ts
git commit -m "feat(calendar): add category color palette module"
```

---

## Task 2: EventBlock — apply palette, drop label, promote time color

**Files:**
- Modify: `frontend/components/calendar/EventBlock.tsx`
- Modify: `frontend/components/__tests__/EventBlock.test.tsx`

- [ ] **Step 1: Update the test file with new behavior**

Replace the entire contents of `frontend/components/__tests__/EventBlock.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import EventBlock from '@/components/calendar/EventBlock'
import type { LaidOutItem } from '@/lib/calendarGrid'
import { CATEGORY_BG, RECOMMENDATION_OPACITY } from '@/lib/categoryColors'

// Helper builder for a timed CalendarEntry-backed grid item.
const eventItem = (overrides: Partial<LaidOutItem> = {}): LaidOutItem => ({
  id: 'evt-1',
  kind: 'event',
  title: 'Jazz Night',
  day: '2026-06-21',
  startMinutes: 18 * 60,
  endMinutes: 20 * 60,
  raw: {
    id: 'ce-1',
    kind: 'saved',
    saved_at: '2026-06-21T00:00:00Z',
    event: { id: 'evt-1', category: 'concerts' } as any,
  } as any,
  column: 0,
  columnCount: 1,
  ...overrides,
})

// Helper builder for a user appointment.
const appointmentItem = (overrides: Partial<LaidOutItem> = {}): LaidOutItem => ({
  id: 'app-1',
  kind: 'appointment',
  title: 'Dentist',
  day: '2026-06-21',
  startMinutes: 9 * 60,
  endMinutes: 10 * 60,
  raw: { id: 'app-1', title: 'Dentist' } as any,
  column: 0,
  columnCount: 1,
  ...overrides,
})

describe('EventBlock', () => {
  it('does not render a "Recommendation:" label anymore', () => {
    render(<EventBlock item={eventItem({ kind: 'recommendation' })} onClick={() => {}} />)
    expect(screen.queryByText(/Recommendation/i)).not.toBeInTheDocument()
  })

  it('applies the category background for events', () => {
    render(<EventBlock item={eventItem({ kind: 'event' })} onClick={() => {}} />)
    const el = screen.getByTestId('event-block-evt-1')
    expect(el.style.background).toContain('rgb(224, 211, 234)') // #e0d3ea = concerts
    expect(el.style.opacity).toBe('') // full opacity for confirmed events
  })

  it('applies category background AND reduced opacity for recommendations', () => {
    render(<EventBlock item={eventItem({ id: 'rec-1', kind: 'recommendation' })} onClick={() => {}} />)
    const el = screen.getByTestId('event-block-rec-1')
    expect(el.style.background).toContain('rgb(224, 211, 234)')
    expect(Number(el.style.opacity)).toBeCloseTo(RECOMMENDATION_OPACITY)
  })

  it('keeps appointment blocks white with dark left border', () => {
    render(<EventBlock item={appointmentItem()} onClick={() => {}} />)
    const el = screen.getByTestId('event-block-app-1')
    expect(el.style.background).toContain('rgb(255, 255, 255)')
    expect(el.style.opacity).toBe('')
  })

  it('applies data-kind="recommendation" attribute', () => {
    render(<EventBlock item={eventItem({ id: 'rec-1', kind: 'recommendation' })} onClick={() => {}} />)
    expect(screen.getByTestId('event-block-rec-1').dataset.kind).toBe('recommendation')
  })

  it('falls back to the "other" swatch when category is missing', () => {
    const item = eventItem({
      id: 'evt-2',
      raw: {
        id: 'ce-2',
        kind: 'saved',
        saved_at: '',
        event: { id: 'evt-2' } as any, // no category field
      } as any,
    })
    render(<EventBlock item={item} onClick={() => {}} />)
    expect(screen.getByTestId('event-block-evt-2').style.background).toContain('rgb(224, 216, 202)') // #e0d8ca
  })
})

// Reference: touching this file marks the recommendation-label removal.
// Sanity constant so imports are used even if a test is later removed.
void CATEGORY_BG
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- components/__tests__/EventBlock.test.tsx`

Expected: FAIL. New assertions on `style.background` will fail because the current component uses Tailwind classes `bg-white` / `bg-gray-300` rather than inline styles.

- [ ] **Step 3: Rewrite EventBlock.tsx**

Replace the contents of `frontend/components/calendar/EventBlock.tsx`:

```tsx
import { HOUR_PX } from './HourGutter'
import type { LaidOutItem } from '@/lib/calendarGrid'
import type { CalendarEntry } from '@/lib/types'
import { categoryBg, RECOMMENDATION_OPACITY } from '@/lib/categoryColors'

function fmtTime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function backgroundFor(item: LaidOutItem): string {
  if (item.kind === 'appointment') return '#ffffff'
  const entry = item.raw as CalendarEntry
  return categoryBg(entry.event?.category)
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
  const borderClasses =
    item.kind === 'appointment'
      ? 'border border-border border-l-[3px] border-text-secondary'
      : 'border border-border border-l-[3px] border-accent-gold'

  return (
    <button
      data-testid={`event-block-${item.id}`}
      data-kind={item.kind}
      onClick={(e) => { e.stopPropagation(); onClick(item) }}
      style={{
        top: startPx, height: heightPx,
        left: `calc(${leftPct}% + 2px)`, width: `calc(${widthPct}% - 4px)`,
        background: backgroundFor(item),
        opacity: isRec ? RECOMMENDATION_OPACITY : undefined,
      }}
      className={`absolute z-10 text-left rounded-md ${borderClasses} px-2 py-1 overflow-hidden hover:shadow-sm cursor-pointer`}
    >
      <p className="text-[11px] font-semibold truncate text-text-primary">{item.title}</p>
      <p className="text-[10px] text-text-primary">
        {fmtTime(item.startMinutes!)}{item.endMinutes != null ? ` – ${fmtTime(item.endMinutes)}` : ''}
      </p>
    </button>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- components/__tests__/EventBlock.test.tsx`

Expected: PASS (6/6).

- [ ] **Step 5: Run the full test suite + type check**

Run in parallel:
- `cd frontend && npm test`
- `cd frontend && npx tsc --noEmit`

Expected: both PASS. (`WeekView.test.tsx` still uses the old behavior only via `getByTestId` — it does not touch the label or bg classes, so it should stay green.)

- [ ] **Step 6: Commit**

```bash
git add frontend/components/calendar/EventBlock.tsx frontend/components/__tests__/EventBlock.test.tsx
git commit -m "feat(calendar): color-code timetable blocks by category, dim recommendations"
```

---

## Task 3: AllDayStrip — same palette + opacity on all-day chips

**Files:**
- Modify: `frontend/components/calendar/AllDayStrip.tsx`

There is no existing test file for AllDayStrip. Rather than scaffolding a new one for a one-line visual change, we ship the change and rely on the shared palette module (already unit-tested in Task 1) plus visual verification in the dev server (Task 4).

- [ ] **Step 1: Update AllDayStrip.tsx**

Replace the contents of `frontend/components/calendar/AllDayStrip.tsx`:

```tsx
'use client'
import type { GridItem, LaidOutItem } from '@/lib/calendarGrid'
import type { CalendarEntry } from '@/lib/types'
import { categoryBg, RECOMMENDATION_OPACITY } from '@/lib/categoryColors'

interface Props {
  days: { key: string }[]
  itemsByDay: Map<string, GridItem[]>
  onItemClick: (item: LaidOutItem) => void
  onAllDayClick: (dayKey: string) => void
}

function chipBackground(it: GridItem): string {
  if (it.kind === 'appointment') return '#ffffff'
  const entry = it.raw as CalendarEntry
  return categoryBg(entry.event?.category)
}

// Shared all-day strip that spans the whole week. It sits outside the vertical
// scroll area so its height doesn't push the timed grid down relative to the
// hour gutter — that misalignment is what caused hour labels to drift.
export default function AllDayStrip({ days, itemsByDay, onItemClick, onAllDayClick }: Props) {
  return (
    <div className="flex border-b border-border bg-bg-surface">
      <div className="w-12 flex-shrink-0 border-r border-border" />
      {days.map(({ key }) => {
        const items = itemsByDay.get(key) ?? []
        return (
          <div
            key={key}
            role="button"
            tabIndex={0}
            onClick={() => onAllDayClick(key)}
            aria-label="Add all-day appointment"
            className="flex-1 min-h-[24px] flex flex-col gap-0.5 p-0.5 border-l border-border cursor-pointer text-left"
          >
            {items.map((it) => {
              const isRec = it.kind === 'recommendation'
              const borderClass =
                it.kind === 'appointment' ? 'border-text-secondary' : 'border-accent-gold'
              return (
                <button
                  key={it.id}
                  data-testid={`allday-block-${it.id}`}
                  data-kind={it.kind}
                  onClick={(e) => {
                    e.stopPropagation()
                    onItemClick({ ...it, column: 0, columnCount: 1 })
                  }}
                  style={{
                    background: chipBackground(it),
                    opacity: isRec ? RECOMMENDATION_OPACITY : undefined,
                  }}
                  className={`text-[10px] truncate rounded px-1 py-0.5 border-l-[3px] ${borderClass} text-left text-text-primary`}
                >
                  {it.title}
                </button>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Run full test suite + type check**

Run in parallel:
- `cd frontend && npm test`
- `cd frontend && npx tsc --noEmit`

Expected: both PASS. `WeekView.test.tsx` finds appointments via `getByTestId('event-block-app-1')` and doesn't assert on class names, so it stays green.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/calendar/AllDayStrip.tsx
git commit -m "feat(calendar): color-code all-day event chips by category"
```

---

## Task 4: Visual verification in dev server

- [ ] **Step 1: Start the dev server**

Run: `cd frontend && npm run dev` (in background)

- [ ] **Step 2: Open the app and check the timetable**

Open the URL Next.js prints (usually `http://localhost:3000`). Navigate to the timetable view.

Verify against the spec (`docs/specs/2026-07-12-timetable-category-colors-design.md`):

- [ ] Confirmed events show category color at full opacity.
- [ ] Recommendations show the same category color at ~55% opacity — no "Recommendation:" label.
- [ ] Appointments remain white with the dark-brown left border.
- [ ] Title and time are both near-black; both stay readable on every category color that appears in your test data.
- [ ] All-day chips at the top of each day also use the category color (or white for appointments).

If any category surfaces a readability issue you didn't see in the mockup, note it and open a follow-up — do not silently tweak hex values in this PR.

- [ ] **Step 3: Stop the dev server**

Kill the background dev-server process.

---

## Self-review notes

- **Spec coverage:** palette table → Task 1; EventBlock changes (bg, opacity, remove label, near-black time) → Task 2; AllDayStrip changes → Task 3; fallback for unknown category → Task 1 test + Task 2 test; visual verification → Task 4.
- **Placeholders:** none. Every code step has full source.
- **Type consistency:** `categoryBg`, `CATEGORY_BG`, and `RECOMMENDATION_OPACITY` names are identical across Tasks 1–3. `EventCategory` and `CalendarEntry` are imported from `@/lib/types`.
- **No new deps.** Palette lives in a new module; nothing else in the codebase imports the old "Recommendation:" text, so no other consumers need updating.
