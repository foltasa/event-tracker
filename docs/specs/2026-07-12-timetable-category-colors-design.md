# Timetable category color-coding — Design

**Date:** 2026-07-12
**Scope:** Frontend only — visual treatment of blocks inside the weekly timetable (`components/calendar/`).
**Non-goals:** No backend or data-model changes. No changes to `EventCard`, `EventDetailOverlay`, feed cards, or any surface outside the calendar.

## Motivation

Timetable slots currently render in only two visual states: white (appointment or event) and gray (recommendation), with a gold left border on events. There is no way to tell a concert from a movie at a glance, and the appointment / event / recommendation distinction leans on subtle border color. Color-coding by category and using opacity for recommendations makes the week readable at a glance.

## Design

### The palette

Backgrounds are soft pastels tuned to the warm-cream page background (`#faf7f2`) so both title (`#1a1208`, near-black) and time (`#1a1208`) stay legible on every color. Appointments intentionally stay white so the user's own items visually separate from imported events.

| Kind / Category | Background | Notes |
|---|---|---|
| Appointment (user)  | `#ffffff` | Keeps existing dark-brown left border (`text-secondary`). |
| `concerts`          | `#e0d3ea` | Soft lavender. |
| `party`             | `#f4e2a8` | Sunny yellow. |
| `comedy`            | `#f5cfc6` | Coral pink. |
| `theater`           | `#e8ccd0` | Dusty rose. |
| `arts`              | `#d3e0cf` | Sage green. |
| `literature`        | `#eee1c6` | Cream / parchment. |
| `film`              | `#cfd8e3` | Slate blue. |
| `family`            | `#b9dcd8` | Soft turquoise — deliberately outside the warm-tan cluster. |
| `food`              | `#edc9b3` | Terracotta. |
| `sports`            | `#cfe1d5` | Pale mint. |
| `outdoor`           | `#dbdfb8` | Soft olive. |
| `other`             | `#e0d8ca` | Warm neutral gray. |

The 12 category keys match the `EventCategory` union in `frontend/lib/types.ts`. Unknown / missing category falls back to the `other` swatch.

### Recommendation vs. confirmed event

A recommendation renders the **same** category background as its confirmed counterpart but at **`opacity: 0.55`**. The beige page bleeds through and produces a washed-out version. This replaces the current dedicated "Recommendation:" label and the gray-300 fill — both are removed.

### Text treatment

- **Title:** `text-text-primary` (`#1a1208`), unchanged.
- **Time:** switches from `text-text-muted` (`#b0956b`) to `text-text-primary` (`#1a1208`). Muted brown was too low-contrast on several category colors; near-black holds up on all of them and matches the title.
- **Left border:**
  - Appointment: `text-secondary` (dark brown) — unchanged.
  - Event / recommendation: `accent-gold` — unchanged. Opacity on the recommendation dims the border along with the fill.
- The `Recommendation:` label block is deleted.

### Where the palette applies

- `components/calendar/EventBlock.tsx` — timed slots inside `DayColumn`.
- `components/calendar/AllDayStrip.tsx` — all-day event chips (also currently white). Same rules apply: appointment stays white, event uses category color, recommendation uses `opacity: 0.55`.

Detail overlay (`EventDetailOverlay.tsx`), feed cards, digest, and any other surface are out of scope.

## Implementation notes

### Where to define the palette

Add a single source of truth as a small helper in `frontend/lib/`, e.g. `categoryColors.ts`, exporting:

```ts
export const CATEGORY_BG: Record<EventCategory, string> = { … hex strings … }
export function categoryBg(category: EventCategory | null | undefined): string
```

Consumed by `EventBlock.tsx` and `AllDayStrip.tsx` via an inline `style={{ background: … }}`. Rationale: hex values with three-digit precision don't map cleanly onto Tailwind tokens and would bloat `tailwind.config.ts` for a single-surface use. Inline style keeps the palette centralized without polluting the design-token layer.

### EventBlock changes

- Remove the `isRec ? 'bg-gray-300' : 'bg-white'` branch.
- Determine background:
  - `appointment` → `#ffffff` (or keep the `bg-white` Tailwind class).
  - `event` / `recommendation` → `categoryBg(item.raw.event.category)`.
- Apply `opacity: 0.55` when `item.kind === 'recommendation'`.
- Drop the "Recommendation:" `<p>` block entirely.
- Change the time `<p>` class from `text-text-muted` to `text-text-primary`.

Border logic (`border`, `border-l-[3px]`, `border-accent-gold` vs. `border-text-secondary`) stays as-is.

### AllDayStrip changes

Currently every chip renders `bg-white border-text-secondary`. Update to mirror EventBlock:

- Appointment: `bg-white` + dark-brown left border (current).
- Event: category background + gold left border.
- Recommendation: category background + gold left border + `opacity: 0.55`.

The chip is a single-line truncated title; no time or Recommendation label to change.

Because `GridItem` on all-day items keeps `raw` (an `Appointment` or `CalendarEntry`), `AllDayStrip` can access `it.raw.event.category` when `it.kind !== 'appointment'`.

### Testing

- Existing `components/__tests__/*` snapshot / behavior tests for calendar blocks should be re-checked; update any that assert on `bg-white` / `bg-gray-300` / `text-text-muted` classes or on the presence of the "Recommendation:" text.
- Add a small unit test for `categoryBg(...)` covering the fallback for `undefined` / unknown category.
- No new backend tests.

## Rollout

Single frontend PR. No feature flag — pure visual change, immediately safe to ship.
