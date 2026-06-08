# Event Tracker — Frontend Dashboard Design

**Status:** Approved · **Date:** 2026-06-08
**Companion documents:** `docs/PRD.md`, `docs/specs/2026-06-08-event-tracker-tech-design.md`, `docs/specs/2026-06-08-data-format-design.md`

---

## 1. Scope

This spec covers the visual design and component architecture for the **Dashboard page** (`/`) of the Event Tracker frontend. It defines the layout, component tree, visual language, data-fetching strategy, and interaction model. Other pages (Onboarding, Calendar, Settings) are out of scope and will be specced separately.

---

## 2. Design decisions

| Decision | Choice |
|---|---|
| Visual theme | Warm & Editorial |
| App shell | Top nav + two-column content area |
| Data fetching | Client-side SWR |
| Event card style | Image Hero (three size variants) |
| Feedback model | Quick 👍/👎 on cards; detailed comment via event detail overlay chat |
| Chat placement | Always-visible right panel |

---

## 3. Visual language

### Palette

| Token | Value | Usage |
|---|---|---|
| `bg-page` | `#faf7f2` | Page background, card backgrounds |
| `bg-surface` | `#f0ebe2` | Nav, section headers, raised surfaces |
| `bg-chat` | `#fdf9f4` | Chat panel background |
| `accent-gold` | `#92763c` | Primary action colour, active states, category badges |
| `accent-gold-light` | `#f5ede0` | Pill backgrounds, subtle highlights |
| `text-primary` | `#1a1208` | Headings, card titles |
| `text-secondary` | `#6b5c3e` | Metadata (time, venue, price) |
| `text-muted` | `#b0956b` | Timestamps, token counts, placeholder text |
| `border` | `#e8e0d4` | All borders |
| `border-active` | `#92763c` | Liked/saved card border highlight |

### Typography

- **Headings / card titles:** Georgia (serif), font-weight 700
- **Body / UI chrome:** System sans-serif (Inter via `next/font`)
- **Justification quotes / AI callouts:** Georgia italic
- **Labels / badges:** sans-serif, uppercase, letter-spacing 1–2px, font-size 9–10px

---

## 4. App shell

### Top navigation (sticky)

```
[ Event Tracker ]  [ Dashboard* ]  [ Calendar ]  [ Settings ]        Hamburg · {date}
```

- Background `bg-surface`, bottom border `border`
- Active tab: `accent-gold` filled pill; inactive: `text-secondary` text only
- Date string right-aligned in `accent-gold` italic

### Two-column layout

```
┌─────────────────────────────────┬──────────────────┐
│  Left column  (flex: 1)         │  Chat panel      │
│  DigestSection                  │  (280px fixed)   │
│  ─────────────                  │                  │
│  FeedFilters                    │                  │
│  FeedSection (scrollable)       │                  │
└─────────────────────────────────┴──────────────────┘
```

- Left column is a flex column; DigestSection has a fixed height, FeedSection takes remaining height and scrolls internally
- Chat panel is always visible at 280px, never collapses

---

## 5. Component tree

```
DashboardPage          "use client" — owns SWR fetches and session state
├── TopNav
├── DigestSection      useSWR("/digest")
│   └── EventCard × N  [variant: digest]
├── FeedFilters        local state (category, date preset, is_free, q)
├── FeedSection        useSWR("/events", infinite)
│   └── EventCard × N  [variant: feed]
├── EventDetailOverlay (portal, shown when activeEventId != null)
│   ├── EventHero
│   ├── EventMetaRow   (venue · price · tags · 👍 👎 · Save)
│   ├── EventDescription (scrollable)
│   ├── AIJustificationCallout
│   └── EventChat      useChat(eventId) — scoped SSE session
│       ├── MessageList
│       ├── TokenUsageBar
│       └── ChatInput
└── ChatPanel          useChat("dashboard") — discovery session
    ├── MessageList
    │   └── EventCard [variant: chat-mini] (when agent returns events)
    ├── TokenUsageBar
    └── ChatInput
```

---

## 6. EventCard — three variants

`EventCard` is a single component accepting a `variant` prop. The `feed` and `chat-mini` variants take `EventWithContext`; the `digest` variant takes `DigestPick` (which wraps `EventCard` + `justification` string) so it can render the AI justification text.

### 6.1 Variant: `digest` (portrait)

Used in the DigestSection horizontal scroll row. Accepts `DigestPick` (not `EventWithContext`) to access the per-pick `justification` field.

- **Layout:** vertical card, ~160px wide, fixed in a horizontal scroll container
- **Image:** top banner, 60px tall, gradient overlay; category badge top-left; venue name bottom-left
- **Body:** title (Georgia serif, 11px bold), datetime + price (9px secondary), AI justification (9px italic, max 2 lines)
- **Actions:** 👍 👎 (border buttons) + Save (gold filled, right-aligned)
- **Liked state:** gold border `border-active` on entire card

### 6.2 Variant: `feed` (landscape strip)

Used in the FeedSection vertical list.

- **Layout:** horizontal card, full width, 68px tall
- **Image:** left strip, 80px wide, gradient; category badge bottom-left
- **Body:** title (11px serif bold, single line ellipsis), datetime + venue + price (9px secondary)
- **Actions:** 👍 👎 + Save pill (right side)
- **Liked state:** gold border; disliked state: reduced opacity (0.5)

### 6.3 Variant: `chat-mini`

Used inline inside chat message bubbles when the agent returns event results.

- **Layout:** compact card inside the chat bubble, ~full bubble width
- **Image:** top banner, 36px tall
- **Body:** title (10px serif bold), datetime + price (9px)
- **Actions:** 👍 👎 + Save (minimal, 9px)
- Clicking opens `EventDetailOverlay` same as other variants

### Shared behaviour

- Clicking the **image, title, or venue** on any variant opens `EventDetailOverlay`
- Clicking 👍/👎 fires an optimistic update via `postFeedback()` — sentiment state updates immediately, reverts on error
- Save fires `saveToCalendar()` optimistically; button changes to "Saved ✓"
- `is_active: false` events render at 50% opacity with a "Event ended" label; interactions disabled

---

## 7. DigestSection

- Horizontal scroll row of `digest`-variant EventCards
- Header: "Today's Picks" (Georgia serif, 14px bold) + generated timestamp (italic muted) + "↻ Refresh" button (calls `refreshDigest()`)
- Loading state: 3 skeleton cards (same dimensions, animated shimmer in `bg-surface`)
- Empty state: "No picks yet — check back after events are loaded." with a manual refresh link
- Separated from the FeedSection by a `2px border` rule

---

## 8. FeedSection & FeedFilters

### Filters

A sticky filter bar between the digest and the feed:

- **Category chips:** All (default) · Music · Tech · Arts · Outdoor · Food · Film · Theater · Family — single select, active chip filled gold
- **Date preset:** dropdown — "Any time" / "Today" / "This week" / "This weekend"
- **Free only:** toggle chip
- **Search:** right-aligned text input, queries `q` param, debounced 300ms

All filter state is local to `FeedFilters`; changes reset the SWR infinite list to page 1.

### Feed list

- Infinite scroll via `useSWRInfinite`; loads next page when user scrolls to within 200px of bottom
- Items separated by a 1px `border` rule
- "Loading more…" spinner in `text-muted` italic at the bottom
- Empty state: "No events match your filters." with a "Clear filters" link

---

## 9. EventDetailOverlay

Rendered as a React portal at the document body level. Opens when `activeEventId` is set in `DashboardPage` state.

### Structure (top to bottom, scrollable body)

1. **HeroImage** — 140px tall, full-width gradient image; category badge + source link (top-left); close button ✕ (top-right); title + datetime (bottom, white text over gradient)
2. **MetaRow** — venue, price, tags in a horizontal row; 👍 👎 + "Save to Calendar" button right-aligned; sticky below hero
3. **Scrollable body:**
   - **EventDescription** — rich text, Georgia serif 12px, 1.75 line-height
   - **AIJustificationCallout** — gold left-border callout block, italic, prefixed with ✦
   - **Divider** with "Chat about this event" label
   - **EventChat message list** — user bubbles (right, `bg-surface` italic) + assistant bubbles (left, white bordered)
4. **ChatInput** — sticky at the bottom of the overlay; placeholder "Ask about this event, or leave a note for the agent…"
5. **TokenUsageBar** — below input, right-aligned, 8px muted text

### EventChat behaviour

- Uses a dedicated `session_id` keyed to `event_id` so the conversation is scoped to this event
- On first open, injects a system context: event title + description + user's taste summary
- User messages that express a sentiment ("loved it", "not my thing", "saving this") trigger `record_feedback()` with the message text as the `comment`
- The agent can also call `save_to_calendar()` on behalf of the user in response to a message like "save this"
- Token usage displayed per message

### Backdrop

- Semi-transparent black overlay (`rgba(26, 18, 8, 0.55)`) covers the dashboard
- Clicking backdrop closes the overlay
- `Escape` key closes the overlay
- Body scroll locked while overlay is open

---

## 10. ChatPanel (discovery)

Always-visible right column (280px), scoped to a `"dashboard"` session separate from any per-event chat.

### Header
"Chat Assistant" (Georgia serif 12px bold) + current model name + today's cost (muted, 9px)

### Message list
- User messages: right-aligned bubble, `bg-surface`, italic
- Assistant messages: left-aligned, white bordered bubble
- Tool running indicator: left-aligned, pulsing gold dot + tool name in italic (e.g. "search_events running…")
- Inline `EventCard` (variant `chat-mini`) rendered inside assistant bubbles when the agent returns event results

### Input
Placeholder "Ask anything about events…"; sends on Enter or ↑ button; disabled while stream is in flight

### TokenUsageBar
Between input and message list footer: "N in · N out · $X.XXXX this message"

---

## 11. Data fetching strategy

All fetching is client-side (SWR). No server components on the dashboard page.

| Data | Hook | Endpoint |
|---|---|---|
| Digest picks | `useSWR("/digest")` | `GET /digest` |
| Event feed | `useSWRInfinite("/events", filters)` | `GET /events?...` |
| Event detail | `useSWR("/events/{id}")` when overlay opens | `GET /events/{id}` |
| Feedback | mutation via `postFeedback()`, optimistic | `POST /feedback` |
| Save to calendar | mutation via `saveToCalendar()`, optimistic | `POST /calendar/{id}` |
| Discovery chat | streaming via `postChat()` | `POST /chat` (SSE) |
| Per-event chat | streaming via `postChat()` with event session_id | `POST /chat` (SSE) |

`NEXT_PUBLIC_MOCK_MODE=true` routes all calls to the fixture files in `frontend/fixtures/`.

---

## 12. Loading and error states

| Component | Loading | Error |
|---|---|---|
| DigestSection | 3 shimmer skeleton cards | Inline error banner with retry |
| FeedSection | Spinner on first load; "Loading more…" on infinite scroll | Inline error with retry |
| EventDetailOverlay | Shimmer hero + meta skeleton | Error message in overlay body |
| ChatPanel / EventChat | Disabled input, no spinner | Inline error bubble in message list |

---

## 13. Accessibility notes

- All interactive elements keyboard-navigable (Tab, Enter, Escape)
- Overlay traps focus while open
- `aria-label` on icon-only buttons (👍 👎 ✕)
- Sufficient colour contrast: all text on `bg-page` meets WCAG AA

---

## 14. Out of scope for this spec

- Onboarding page (`/onboarding`)
- Calendar page (`/calendar`)
- Settings page (`/settings`)
- Animations and transition details (left to implementation judgment)
- Responsive / mobile layout (local-only MVP, desktop assumed)
