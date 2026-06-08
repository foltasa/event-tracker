# Event Tracker Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Dashboard page — Today's Picks digest, scrollable event feed, always-visible chat panel, and event detail overlay with per-event chat.

**Architecture:** Client-only Next.js 14 App Router page (`"use client"`). SWR 2 handles all data fetching with optimistic mutation for feedback and calendar saves. The event detail overlay renders as a React portal. Two independent chat sessions (discovery panel + per-event) share a `useChat` hook.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS 3, SWR 2, Vitest 1 + @testing-library/react 14

---

## File map

| Status | Path | Responsibility |
|---|---|---|
| modify | `frontend/package.json` | add swr, vitest, testing deps |
| create | `frontend/vitest.config.ts` | vitest + jsdom + @ alias |
| create | `frontend/vitest.setup.ts` | jest-dom + IntersectionObserver mock |
| modify | `frontend/tailwind.config.ts` | add warm editorial color tokens |
| modify | `frontend/app/globals.css` | editorial base styles + shimmer keyframe |
| create | `frontend/lib/swr-provider.tsx` | client SWRConfig wrapper (cache isolation) |
| modify | `frontend/app/layout.tsx` | wrap body in SWRProvider |
| create | `frontend/components/TopNav.tsx` | sticky nav bar |
| create | `frontend/components/SkeletonCard.tsx` | shimmer loading placeholder |
| create | `frontend/components/EventCard.tsx` | image-hero card, three variants |
| create | `frontend/components/DigestSection.tsx` | horizontal scroll digest row |
| create | `frontend/components/FeedFilters.tsx` | category chips, date, free toggle, search |
| create | `frontend/components/FeedSection.tsx` | infinite-scroll event list |
| create | `frontend/hooks/useChat.ts` | streaming chat session state |
| create | `frontend/components/ChatPanel.tsx` | discovery chat right column |
| create | `frontend/components/EventDetailOverlay.tsx` | portal overlay with per-event chat |
| modify | `frontend/app/page.tsx` | DashboardPage: wires all components |
| create | `frontend/components/__tests__/EventCard.test.tsx` | |
| create | `frontend/components/__tests__/DigestSection.test.tsx` | |
| create | `frontend/components/__tests__/FeedFilters.test.tsx` | |
| create | `frontend/hooks/__tests__/useChat.test.ts` | |
| create | `frontend/components/__tests__/ChatPanel.test.tsx` | |
| create | `frontend/components/__tests__/EventDetailOverlay.test.tsx` | |

---

## Shared test fixtures

Every test file imports these. Define them once at the top of each test file (do not create a shared fixture module — keep tests self-contained).

```ts
import type { DigestPick, DigestResponse, EventCard, EventWithContext, EventsFeedResponse } from '@/lib/types'

const mockEvent: EventCard = {
  id: 'evt_001', title: 'Jazz Night at Mojo Club', summary: 'Intimate trio set',
  start_datetime: '2026-06-09T20:00:00+02:00', end_datetime: null,
  venue_name: 'Mojo Club', venue_address: 'Reeperbahn 1, Hamburg',
  category: 'music', tags: ['jazz'], price_min: 18, price_max: 24,
  is_free: false, currency: 'EUR',
  image_url: 'https://images.example.com/mojo.jpg',
  source_url: 'https://eventbrite.de/123', source: 'eventbrite', is_active: true,
}
const mockEventCtx: EventWithContext = {
  ...mockEvent, user_sentiment: null, user_comment: null, is_saved: false,
}
const mockPick: DigestPick = {
  event: mockEvent, justification: 'You liked intimate venues last month.',
}
const mockDigest: DigestResponse = {
  date: '2026-06-08', picks: [mockPick],
  generated_at: '2026-06-08T07:42:11+02:00', is_cached: true,
}
const mockFeed: EventsFeedResponse = {
  events: [mockEventCtx], total: 1, page: 1, page_size: 20,
}
```

---

## Task 1: Install dependencies and set up test framework

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/vitest.setup.ts`

- [ ] **Step 1.1: Install runtime and dev dependencies**

Run in `frontend/`:
```bash
npm install swr
npm install --save-dev vitest @vitest/coverage-v8 @testing-library/react @testing-library/user-event @testing-library/jest-dom @vitejs/plugin-react jsdom
```

Expected: `package.json` updated with new deps, no errors.

- [ ] **Step 1.2: Add test script to package.json**

In `frontend/package.json`, update `"scripts"`:
```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

- [ ] **Step 1.3: Create vitest.config.ts**

Create `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './vitest.setup.ts',
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './') },
  },
})
```

- [ ] **Step 1.4: Create vitest.setup.ts**

Create `frontend/vitest.setup.ts`:
```ts
import '@testing-library/jest-dom'

// IntersectionObserver is not available in jsdom
class MockIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  constructor(public callback: IntersectionObserverCallback) {}
}
Object.defineProperty(window, 'IntersectionObserver', {
  writable: true,
  value: MockIntersectionObserver,
})
```

- [ ] **Step 1.5: Verify test framework works**

Create `frontend/components/__tests__/smoke.test.ts` temporarily:
```ts
describe('smoke', () => {
  it('runs', () => expect(1 + 1).toBe(2))
})
```

Run:
```bash
cd frontend && npm test
```
Expected: `1 passed`.

Delete `frontend/components/__tests__/smoke.test.ts`.

- [ ] **Step 1.6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/vitest.setup.ts
git commit -m "chore: add SWR and Vitest test framework to frontend"
```

---

## Task 2: Tailwind color tokens and global styles

**Files:**
- Modify: `frontend/tailwind.config.ts`
- Modify: `frontend/app/globals.css`

- [ ] **Step 2.1: Write the failing test**

Create `frontend/components/__tests__/tokens.test.ts`:
```ts
import config from '@/tailwind.config'

describe('tailwind config', () => {
  it('exposes accent-gold token', () => {
    const colors = (config.theme?.extend as any)?.colors
    expect(colors?.['accent-gold']).toBe('#92763c')
  })
  it('exposes bg-page token', () => {
    const colors = (config.theme?.extend as any)?.colors
    expect(colors?.['bg-page']).toBe('#faf7f2')
  })
})
```

Run: `npm test -- tokens`
Expected: FAIL — `colors` is undefined.

- [ ] **Step 2.2: Update tailwind.config.ts**

Replace `frontend/tailwind.config.ts`:
```ts
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        'bg-page':          '#faf7f2',
        'bg-surface':       '#f0ebe2',
        'bg-chat':          '#fdf9f4',
        'accent-gold':      '#92763c',
        'accent-gold-light':'#f5ede0',
        'text-primary':     '#1a1208',
        'text-secondary':   '#6b5c3e',
        'text-muted':       '#b0956b',
        'border-warm':      '#e8e0d4',
        'border-active':    '#92763c',
      },
      fontFamily: {
        serif: ['Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
export default config
```

- [ ] **Step 2.3: Run test — expect PASS**

```bash
npm test -- tokens
```
Expected: `2 passed`.

- [ ] **Step 2.4: Update globals.css**

Replace `frontend/app/globals.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --font-sans: 'Inter', system-ui, sans-serif;
}

body {
  background-color: #faf7f2;
  color: #1a1208;
  font-family: var(--font-sans);
}

@keyframes shimmer {
  0%   { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

.shimmer {
  background: linear-gradient(90deg, #f0ebe2 25%, #faf7f2 50%, #f0ebe2 75%);
  background-size: 800px 100%;
  animation: shimmer 1.4s infinite;
}
```

- [ ] **Step 2.5: Commit**

```bash
git add frontend/tailwind.config.ts frontend/app/globals.css frontend/components/__tests__/tokens.test.ts
git commit -m "feat: add warm editorial Tailwind tokens and global styles"
```

---

## Task 3: SWRProvider and layout update

**Files:**
- Create: `frontend/lib/swr-provider.tsx`
- Modify: `frontend/app/layout.tsx`

- [ ] **Step 3.1: Create swr-provider.tsx**

Create `frontend/lib/swr-provider.tsx`:
```tsx
'use client'
import { SWRConfig } from 'swr'

export default function SWRProvider({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ revalidateOnFocus: false, shouldRetryOnError: false }}>
      {children}
    </SWRConfig>
  )
}
```

- [ ] **Step 3.2: Update layout.tsx**

Replace `frontend/app/layout.tsx`:
```tsx
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import SWRProvider from '@/lib/swr-provider'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Event Tracker',
  description: 'Personalized Hamburg event recommendations',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <SWRProvider>{children}</SWRProvider>
      </body>
    </html>
  )
}
```

- [ ] **Step 3.3: Commit**

```bash
git add frontend/lib/swr-provider.tsx frontend/app/layout.tsx
git commit -m "feat: add SWRProvider wrapper to app layout"
```

---

## Task 4: TopNav component

**Files:**
- Create: `frontend/components/TopNav.tsx`

TopNav receives the active route and the current date string as props (no router dependency — keeps it testable).

- [ ] **Step 4.1: Write the failing test**

Create `frontend/components/__tests__/TopNav.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import TopNav from '@/components/TopNav'

describe('TopNav', () => {
  it('renders brand name', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Event Tracker')).toBeInTheDocument()
  })

  it('applies active style to current page link', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    const dashLink = screen.getByText('Dashboard')
    expect(dashLink).toHaveClass('bg-accent-gold')
  })

  it('does not apply active style to inactive links', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Calendar')).not.toHaveClass('bg-accent-gold')
  })

  it('renders date string', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Hamburg · June 8')).toBeInTheDocument()
  })
})
```

Run: `npm test -- TopNav`
Expected: FAIL — module not found.

- [ ] **Step 4.2: Implement TopNav.tsx**

Create `frontend/components/TopNav.tsx`:
```tsx
import Link from 'next/link'

type ActivePage = 'dashboard' | 'calendar' | 'settings'

const LINKS: { href: string; label: string; page: ActivePage }[] = [
  { href: '/',          label: 'Dashboard', page: 'dashboard' },
  { href: '/calendar',  label: 'Calendar',  page: 'calendar'  },
  { href: '/settings',  label: 'Settings',  page: 'settings'  },
]

export default function TopNav({ active, date }: { active: ActivePage; date: string }) {
  return (
    <nav className="sticky top-0 z-30 flex items-center gap-1 px-5 py-2.5 bg-bg-surface border-b border-border-warm">
      <span className="font-serif font-bold text-base text-text-primary mr-5">
        Event Tracker
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

- [ ] **Step 4.3: Run test — expect PASS**

```bash
npm test -- TopNav
```
Expected: `4 passed`.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/components/TopNav.tsx frontend/components/__tests__/TopNav.test.tsx
git commit -m "feat: add TopNav component"
```

---

## Task 5: SkeletonCard loading placeholder

**Files:**
- Create: `frontend/components/SkeletonCard.tsx`

- [ ] **Step 5.1: Create SkeletonCard.tsx**

No test needed — purely presentational, no logic.

Create `frontend/components/SkeletonCard.tsx`:
```tsx
export default function SkeletonCard({ variant }: { variant: 'digest' | 'feed' }) {
  if (variant === 'digest') {
    return (
      <div className="min-w-[160px] rounded-lg border border-border-warm overflow-hidden flex-shrink-0">
        <div className="h-[60px] shimmer" />
        <div className="p-2 space-y-2">
          <div className="h-3 rounded shimmer" />
          <div className="h-2 w-2/3 rounded shimmer" />
          <div className="h-2 rounded shimmer" />
        </div>
      </div>
    )
  }
  return (
    <div className="flex h-[68px] rounded-lg border border-border-warm overflow-hidden">
      <div className="w-20 shimmer flex-shrink-0" />
      <div className="flex-1 p-2 space-y-2">
        <div className="h-3 rounded shimmer" />
        <div className="h-2 w-1/2 rounded shimmer" />
      </div>
    </div>
  )
}
```

- [ ] **Step 5.2: Commit**

```bash
git add frontend/components/SkeletonCard.tsx
git commit -m "feat: add SkeletonCard shimmer loading placeholder"
```

---

## Task 6: EventCard component

**Files:**
- Create: `frontend/components/EventCard.tsx`
- Create: `frontend/components/__tests__/EventCard.test.tsx`

`EventCard` accepts either a `DigestPick` (variant `digest`) or `EventWithContext` (variants `feed` / `chat-mini`).

- [ ] **Step 6.1: Write the failing test**

Create `frontend/components/__tests__/EventCard.test.tsx`:
```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import type { DigestPick, EventCard as EventCardType, EventWithContext } from '@/lib/types'
import EventCard from '@/components/EventCard'

const mockEvent: EventCardType = {
  id: 'evt_001', title: 'Jazz Night at Mojo Club', summary: 'Intimate trio set',
  start_datetime: '2026-06-09T20:00:00+02:00', end_datetime: null,
  venue_name: 'Mojo Club', venue_address: 'Reeperbahn 1',
  category: 'music', tags: ['jazz'], price_min: 18, price_max: 24,
  is_free: false, currency: 'EUR',
  image_url: 'https://images.example.com/mojo.jpg',
  source_url: 'https://eventbrite.de/123', source: 'eventbrite', is_active: true,
}
const mockEventCtx: EventWithContext = {
  ...mockEvent, user_sentiment: null, user_comment: null, is_saved: false,
}
const mockPick: DigestPick = {
  event: mockEvent, justification: 'You liked intimate venues last month.',
}

describe('EventCard feed variant', () => {
  it('renders title and venue', () => {
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Jazz Night at Mojo Club')).toBeInTheDocument()
    expect(screen.getByText(/Mojo Club/)).toBeInTheDocument()
  })

  it('calls onCardClick when title clicked', () => {
    const onCardClick = vi.fn()
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={onCardClick} onFeedback={vi.fn()} onSave={vi.fn()} />)
    fireEvent.click(screen.getByText('Jazz Night at Mojo Club'))
    expect(onCardClick).toHaveBeenCalledWith('evt_001')
  })

  it('calls onFeedback with like when thumbs up clicked', () => {
    const onFeedback = vi.fn()
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={onFeedback} onSave={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Like'))
    expect(onFeedback).toHaveBeenCalledWith('evt_001', 'like')
  })

  it('calls onFeedback with dislike when thumbs down clicked', () => {
    const onFeedback = vi.fn()
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={onFeedback} onSave={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Dislike'))
    expect(onFeedback).toHaveBeenCalledWith('evt_001', 'dislike')
  })

  it('calls onSave when Save clicked', () => {
    const onSave = vi.fn()
    render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={onSave} />)
    fireEvent.click(screen.getByText('Save'))
    expect(onSave).toHaveBeenCalledWith('evt_001')
  })

  it('shows Saved when is_saved is true', () => {
    render(<EventCard variant="feed" data={{ ...mockEventCtx, is_saved: true }} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Saved ✓')).toBeInTheDocument()
  })

  it('applies gold border when liked', () => {
    const { container } = render(
      <EventCard variant="feed" data={{ ...mockEventCtx, user_sentiment: 'like' }} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    expect(container.firstChild).toHaveClass('border-border-active')
  })

  it('renders at reduced opacity and disables interactions when inactive', () => {
    const { container } = render(
      <EventCard variant="feed" data={{ ...mockEventCtx, is_active: false }} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    expect(container.firstChild).toHaveClass('opacity-50')
  })
})

describe('EventCard digest variant', () => {
  it('renders justification text', () => {
    render(<EventCard variant="digest" data={mockPick} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('You liked intimate venues last month.')).toBeInTheDocument()
  })
})

describe('EventCard chat-mini variant', () => {
  it('renders title', () => {
    render(<EventCard variant="chat-mini" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Jazz Night at Mojo Club')).toBeInTheDocument()
  })
})
```

Run: `npm test -- EventCard`
Expected: FAIL — module not found.

- [ ] **Step 6.2: Implement EventCard.tsx**

Create `frontend/components/EventCard.tsx`:
```tsx
'use client'
import type { DigestPick, EventWithContext, Sentiment } from '@/lib/types'

type FeedOrMini = { variant: 'feed' | 'chat-mini'; data: EventWithContext }
type DigestVariant = { variant: 'digest'; data: DigestPick }
type Props = (FeedOrMini | DigestVariant) & {
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatPrice(min: number | null, max: number | null, isFree: boolean) {
  if (isFree) return 'Free'
  if (min == null) return ''
  if (max != null && max !== min) return `€${min}–${max}`
  return `€${min}`
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider font-semibold bg-accent-gold text-bg-page">
      {category}
    </span>
  )
}

function FeedbackButtons({
  id, sentiment, onFeedback, disabled,
}: {
  id: string; sentiment: string | null; onFeedback: (id: string, s: Sentiment) => void; disabled: boolean
}) {
  return (
    <>
      <button
        aria-label="Like"
        disabled={disabled}
        onClick={(e) => { e.stopPropagation(); onFeedback(id, 'like') }}
        className={`rounded border px-1.5 py-0.5 text-xs ${sentiment === 'like' ? 'bg-accent-gold border-accent-gold text-bg-page' : 'bg-white border-border-warm'}`}
      >
        👍
      </button>
      <button
        aria-label="Dislike"
        disabled={disabled}
        onClick={(e) => { e.stopPropagation(); onFeedback(id, 'dislike') }}
        className={`rounded border px-1.5 py-0.5 text-xs ${sentiment === 'dislike' ? 'bg-text-secondary border-text-secondary text-bg-page' : 'bg-white border-border-warm'}`}
      >
        👎
      </button>
    </>
  )
}

export default function EventCard({ variant, data, onCardClick, onFeedback, onSave }: Props) {
  const event = variant === 'digest' ? (data as DigestPick).event : (data as EventWithContext)
  const ctx   = variant !== 'digest' ? (data as EventWithContext) : null
  const justification = variant === 'digest' ? (data as DigestPick).justification : null

  const isActive   = event.is_active
  const sentiment  = ctx?.user_sentiment ?? null
  const isSaved    = ctx?.is_saved ?? false
  const priceStr   = formatPrice(event.price_min, event.price_max, event.is_free)
  const dateStr    = formatDate(event.start_datetime)

  const borderClass = sentiment === 'like' ? 'border-border-active' : 'border-border-warm'
  const opacityClass = isActive ? '' : 'opacity-50 pointer-events-none'

  const imageBanner = (height: string) => (
    <div
      className={`relative ${height} flex-shrink-0 cursor-pointer`}
      style={event.image_url
        ? { backgroundImage: `url(${event.image_url})`, backgroundSize: 'cover', backgroundPosition: 'center' }
        : { background: 'linear-gradient(135deg, #d4b896, #b8906a)' }
      }
      onClick={() => isActive && onCardClick(event.id)}
    >
      <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/50" />
      <div className="absolute bottom-1 left-1.5">
        <CategoryBadge category={event.category} />
      </div>
    </div>
  )

  if (variant === 'digest') {
    return (
      <div className={`min-w-[160px] rounded-lg border ${borderClass} ${opacityClass} overflow-hidden flex-shrink-0 bg-white`}>
        {imageBanner('h-[60px]')}
        <div className="p-2">
          <button
            className="font-serif text-[11px] font-bold text-text-primary text-left w-full"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary mt-0.5">
            {dateStr}{priceStr && ` · ${priceStr}`}
          </p>
          {justification && (
            <p className="text-[9px] italic text-text-primary mt-1 line-clamp-2">{justification}</p>
          )}
          <div className="flex gap-1 mt-1.5 items-center">
            <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
            <button
              onClick={(e) => { e.stopPropagation(); onSave(event.id) }}
              className="ml-auto rounded bg-accent-gold text-bg-page text-[9px] px-1.5 py-0.5"
            >
              {isSaved ? 'Saved ✓' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (variant === 'chat-mini') {
    return (
      <div className={`rounded-lg border ${borderClass} ${opacityClass} overflow-hidden bg-bg-page w-full`}>
        {imageBanner('h-9')}
        <div className="p-1.5">
          <button
            className="font-serif text-[10px] font-bold text-text-primary text-left w-full"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary">{dateStr}{priceStr && ` · ${priceStr}`}</p>
          <div className="flex gap-1 mt-1">
            <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
            <button
              onClick={(e) => { e.stopPropagation(); onSave(event.id) }}
              className="ml-auto rounded bg-accent-gold text-bg-page text-[8px] px-1.5 py-0.5"
            >
              {isSaved ? 'Saved ✓' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // variant === 'feed'
  return (
    <div className={`flex h-[68px] rounded-lg border ${borderClass} ${opacityClass} overflow-hidden bg-white`}>
      {imageBanner('w-20')}
      <div className="flex-1 flex flex-col justify-between p-2 min-w-0">
        <div>
          <button
            className="font-serif text-[11px] font-bold text-text-primary text-left w-full truncate"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary">
            {event.venue_name && `${event.venue_name} · `}{dateStr}{priceStr && ` · ${priceStr}`}
          </p>
        </div>
        <div className="flex gap-1 items-center">
          <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
          <button
            onClick={(e) => { e.stopPropagation(); onSave(event.id) }}
            className="ml-auto rounded bg-accent-gold-light text-accent-gold text-[9px] px-1.5 py-0.5"
          >
            {isSaved ? 'Saved ✓' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 6.3: Run tests — expect PASS**

```bash
npm test -- EventCard
```
Expected: `9 passed`.

- [ ] **Step 6.4: Commit**

```bash
git add frontend/components/EventCard.tsx frontend/components/__tests__/EventCard.test.tsx
git commit -m "feat: add EventCard component with digest, feed and chat-mini variants"
```

---

## Task 7: DigestSection component

**Files:**
- Create: `frontend/components/DigestSection.tsx`
- Create: `frontend/components/__tests__/DigestSection.test.tsx`

- [ ] **Step 7.1: Write the failing test**

Create `frontend/components/__tests__/DigestSection.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import type { DigestResponse, EventCard as EventCardType, DigestPick } from '@/lib/types'
import DigestSection from '@/components/DigestSection'

vi.mock('@/lib/api', () => ({
  getDigest: vi.fn(),
  refreshDigest: vi.fn(),
}))
import { getDigest, refreshDigest } from '@/lib/api'

const mockEvent: EventCardType = {
  id: 'evt_001', title: 'Jazz Night at Mojo Club', summary: null,
  start_datetime: '2026-06-09T20:00:00+02:00', end_datetime: null,
  venue_name: 'Mojo Club', venue_address: null, category: 'music', tags: [],
  price_min: 18, price_max: null, is_free: false, currency: 'EUR',
  image_url: null, source_url: 'https://eb.com/1', source: 'eventbrite', is_active: true,
}
const mockPick: DigestPick = { event: mockEvent, justification: 'Great match.' }
const mockDigest: DigestResponse = {
  date: '2026-06-08', picks: [mockPick],
  generated_at: '2026-06-08T07:42:11+02:00', is_cached: true,
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
    {children}
  </SWRConfig>
)

describe('DigestSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows skeleton cards while loading', () => {
    vi.mocked(getDigest).mockReturnValue(new Promise(() => {}))
    const { container } = render(<DigestSection onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    expect(container.querySelectorAll('.shimmer').length).toBeGreaterThan(0)
  })

  it('renders pick cards after loading', async () => {
    vi.mocked(getDigest).mockResolvedValue(mockDigest)
    render(<DigestSection onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    await screen.findByText('Jazz Night at Mojo Club')
    expect(screen.getByText('Great match.')).toBeInTheDocument()
  })

  it('shows empty state when no picks', async () => {
    vi.mocked(getDigest).mockResolvedValue({ ...mockDigest, picks: [] })
    render(<DigestSection onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    await screen.findByText(/No picks yet/)
  })

  it('calls refreshDigest when Refresh button clicked', async () => {
    vi.mocked(getDigest).mockResolvedValue(mockDigest)
    vi.mocked(refreshDigest).mockResolvedValue(mockDigest)
    render(<DigestSection onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    await screen.findByText('Jazz Night at Mojo Club')
    fireEvent.click(screen.getByText('↻ Refresh'))
    await waitFor(() => expect(refreshDigest).toHaveBeenCalledOnce())
  })
})
```

Run: `npm test -- DigestSection`
Expected: FAIL — module not found.

- [ ] **Step 7.2: Implement DigestSection.tsx**

Create `frontend/components/DigestSection.tsx`:
```tsx
'use client'
import useSWR from 'swr'
import { getDigest, refreshDigest as refreshDigestApi } from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import EventCard from './EventCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

export default function DigestSection({ onCardClick, onFeedback, onSave }: Props) {
  const { data, isLoading, error, mutate } = useSWR('/digest', getDigest)

  async function handleRefresh() {
    const fresh = await refreshDigestApi()
    mutate(fresh, false)
  }

  return (
    <div className="flex-shrink-0 border-b-2 border-border-warm bg-bg-page">
      <div className="flex items-baseline justify-between px-5 pt-4 pb-2">
        <div className="flex items-baseline gap-2">
          <span className="font-serif font-bold text-sm text-text-primary">Today's Picks</span>
          {data && (
            <span className="text-[10px] italic text-text-muted">
              {data.picks.length} picks · generated {new Date(data.generated_at).toLocaleTimeString('en-DE', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="text-[10px] text-accent-gold border border-border-warm rounded px-2 py-0.5 hover:bg-accent-gold-light"
        >
          ↻ Refresh
        </button>
      </div>

      <div className="flex gap-2.5 overflow-x-auto px-5 pb-4">
        {isLoading && Array.from({ length: 3 }).map((_, i) => (
          <SkeletonCard key={i} variant="digest" />
        ))}

        {error && (
          <p className="text-[10px] text-red-600 italic py-2">
            Could not load picks.{' '}
            <button onClick={() => mutate()} className="text-accent-gold underline">Retry</button>
          </p>
        )}

        {!isLoading && !error && data?.picks.length === 0 && (
          <p className="text-[10px] text-text-muted italic py-2">
            No picks yet — check back after events are loaded.{' '}
            <button onClick={handleRefresh} className="text-accent-gold underline">Refresh now</button>
          </p>
        )}

        {data?.picks.map((pick) => (
          <EventCard
            key={pick.event.id}
            variant="digest"
            data={pick}
            onCardClick={onCardClick}
            onFeedback={onFeedback}
            onSave={onSave}
          />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 7.3: Run tests — expect PASS**

```bash
npm test -- DigestSection
```
Expected: `4 passed`.

- [ ] **Step 7.4: Commit**

```bash
git add frontend/components/DigestSection.tsx frontend/components/__tests__/DigestSection.test.tsx
git commit -m "feat: add DigestSection with SWR loading, picks display, and refresh"
```

---

## Task 8: FeedFilters component

**Files:**
- Create: `frontend/components/FeedFilters.tsx`
- Create: `frontend/components/__tests__/FeedFilters.test.tsx`

`FeedFilters` is controlled — it receives current filter state and an `onChange` callback.

- [ ] **Step 8.1: Write the failing test**

Create `frontend/components/__tests__/FeedFilters.test.tsx`:
```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import FeedFilters from '@/components/FeedFilters'
import type { FeedFilterState } from '@/components/FeedFilters'

const defaultFilters: FeedFilterState = {
  category: null, datePreset: 'any', isFree: false, q: '',
}

describe('FeedFilters', () => {
  it('renders All chip as active by default', () => {
    render(<FeedFilters filters={defaultFilters} onChange={vi.fn()} />)
    expect(screen.getByText('All')).toHaveClass('bg-accent-gold')
  })

  it('calls onChange with new category when chip clicked', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={defaultFilters} onChange={onChange} />)
    fireEvent.click(screen.getByText('Music'))
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, category: 'music' })
  })

  it('calls onChange with null category when All clicked', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={{ ...defaultFilters, category: 'music' }} onChange={onChange} />)
    fireEvent.click(screen.getByText('All'))
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, category: null })
  })

  it('calls onChange with isFree true when Free chip clicked', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={defaultFilters} onChange={onChange} />)
    fireEvent.click(screen.getByText('Free only'))
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, isFree: true })
  })

  it('calls onChange with updated datePreset when dropdown changed', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={defaultFilters} onChange={onChange} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'this-week' } })
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, datePreset: 'this-week' })
  })
})
```

Run: `npm test -- FeedFilters`
Expected: FAIL — module not found.

- [ ] **Step 8.2: Implement FeedFilters.tsx**

Create `frontend/components/FeedFilters.tsx`:
```tsx
'use client'
import type { EventCategory } from '@/lib/types'

export type DatePreset = 'any' | 'today' | 'this-week' | 'this-weekend'

export interface FeedFilterState {
  category: EventCategory | null
  datePreset: DatePreset
  isFree: boolean
  q: string
}

const CATEGORIES: EventCategory[] = ['music','arts','food','sports','tech','outdoor','film','theater','family']

interface Props {
  filters: FeedFilterState
  onChange: (f: FeedFilterState) => void
}

export default function FeedFilters({ filters, onChange }: Props) {
  function chip(label: string, active: boolean, onClick: () => void) {
    return (
      <button
        key={label}
        onClick={onClick}
        className={`rounded px-2 py-0.5 text-[10px] cursor-pointer ${active ? 'bg-accent-gold text-bg-page font-semibold' : 'border border-border-warm text-text-secondary hover:bg-accent-gold-light'}`}
      >
        {label}
      </button>
    )
  }

  return (
    <div className="sticky flex flex-wrap items-center gap-1.5 px-5 py-2 border-b border-border-warm bg-bg-page">
      <span className="text-[9px] uppercase tracking-widest text-accent-gold mr-1">Filter:</span>

      {chip('All', filters.category === null, () => onChange({ ...filters, category: null }))}
      {CATEGORIES.map((cat) =>
        chip(cat.charAt(0).toUpperCase() + cat.slice(1), filters.category === cat, () =>
          onChange({ ...filters, category: cat })
        )
      )}

      {chip('Free only', filters.isFree, () => onChange({ ...filters, isFree: !filters.isFree }))}

      <select
        value={filters.datePreset}
        onChange={(e) => onChange({ ...filters, datePreset: e.target.value as DatePreset })}
        className="ml-1 text-[10px] border border-border-warm rounded px-1.5 py-0.5 bg-white text-text-secondary"
      >
        <option value="any">Any time</option>
        <option value="today">Today</option>
        <option value="this-week">This week</option>
        <option value="this-weekend">This weekend</option>
      </select>

      <input
        type="text"
        value={filters.q}
        onChange={(e) => onChange({ ...filters, q: e.target.value })}
        placeholder="🔍 Search events..."
        className="ml-auto text-[10px] border border-border-warm rounded px-2 py-0.5 bg-white text-text-primary w-32"
      />
    </div>
  )
}
```

- [ ] **Step 8.3: Run tests — expect PASS**

```bash
npm test -- FeedFilters
```
Expected: `5 passed`.

- [ ] **Step 8.4: Commit**

```bash
git add frontend/components/FeedFilters.tsx frontend/components/__tests__/FeedFilters.test.tsx
git commit -m "feat: add FeedFilters controlled component"
```

---

## Task 9: FeedSection component

**Files:**
- Create: `frontend/components/FeedSection.tsx`

FeedSection uses `useSWRInfinite`. The search input is debounced 300ms inside a `useEffect`. The `IntersectionObserver` watches a sentinel `<div>` at the bottom of the list.

- [ ] **Step 9.1: Write the failing test**

Create `frontend/components/__tests__/FeedSection.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { SWRConfig } from 'swr'
import type { EventCard as EventCardType, EventWithContext, EventsFeedResponse } from '@/lib/types'
import FeedSection from '@/components/FeedSection'
import type { FeedFilterState } from '@/components/FeedFilters'

vi.mock('@/lib/api', () => ({
  getEvents: vi.fn(),
}))
import { getEvents } from '@/lib/api'

const mockEvent: EventCardType = {
  id: 'evt_001', title: 'Jazz Night', summary: null,
  start_datetime: '2026-06-09T20:00:00+02:00', end_datetime: null,
  venue_name: 'Mojo Club', venue_address: null, category: 'music', tags: [],
  price_min: 18, price_max: null, is_free: false, currency: 'EUR',
  image_url: null, source_url: 'https://eb.com/1', source: 'eventbrite', is_active: true,
}
const mockEventCtx: EventWithContext = { ...mockEvent, user_sentiment: null, user_comment: null, is_saved: false }
const mockFeed: EventsFeedResponse = { events: [mockEventCtx], total: 1, page: 1, page_size: 20 }

const defaultFilters: FeedFilterState = { category: null, datePreset: 'any', isFree: false, q: '' }

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
    {children}
  </SWRConfig>
)

describe('FeedSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders events after loading', async () => {
    vi.mocked(getEvents).mockResolvedValue(mockFeed)
    render(<FeedSection filters={defaultFilters} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    await screen.findByText('Jazz Night')
  })

  it('shows empty state when no events', async () => {
    vi.mocked(getEvents).mockResolvedValue({ ...mockFeed, events: [], total: 0 })
    render(<FeedSection filters={defaultFilters} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />, { wrapper })
    await screen.findByText(/No events match/)
  })
})
```

Run: `npm test -- FeedSection`
Expected: FAIL — module not found.

- [ ] **Step 9.2: Implement FeedSection.tsx**

Create `frontend/components/FeedSection.tsx`:
```tsx
'use client'
import { useEffect, useRef, useState } from 'react'
import useSWRInfinite from 'swr/infinite'
import { getEvents } from '@/lib/api'
import type { EventsFeedResponse, Sentiment } from '@/lib/types'
import type { FeedFilterState } from './FeedFilters'
import EventCard from './EventCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  filters: FeedFilterState
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

function filtersToQuery(filters: FeedFilterState) {
  const q: Record<string, string> = {}
  if (filters.category) q.category = filters.category
  if (filters.isFree) q.is_free = 'true'
  if (filters.q)      q.q = filters.q
  if (filters.datePreset === 'today') {
    q.date_from = new Date().toISOString().slice(0, 10)
    q.date_to   = new Date().toISOString().slice(0, 10)
  } else if (filters.datePreset === 'this-week') {
    const now  = new Date()
    const end  = new Date(now); end.setDate(now.getDate() + 7)
    q.date_from = now.toISOString().slice(0, 10)
    q.date_to   = end.toISOString().slice(0, 10)
  } else if (filters.datePreset === 'this-weekend') {
    const now = new Date()
    const day = now.getDay()
    const sat = new Date(now); sat.setDate(now.getDate() + ((6 - day + 7) % 7))
    const sun = new Date(sat); sun.setDate(sat.getDate() + 1)
    q.date_from = sat.toISOString().slice(0, 10)
    q.date_to   = sun.toISOString().slice(0, 10)
  }
  return q
}

export default function FeedSection({ filters, onCardClick, onFeedback, onSave }: Props) {
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [debouncedFilters, setDebouncedFilters] = useState(filters)

  useEffect(() => {
    const id = setTimeout(() => setDebouncedFilters(filters), 300)
    return () => clearTimeout(id)
  }, [filters])

  const getKey = (pageIndex: number, prev: EventsFeedResponse | null) => {
    if (prev && prev.events.length < prev.page_size) return null
    return ['/events', debouncedFilters, pageIndex + 1]
  }

  const { data, isLoading, isValidating, size, setSize } = useSWRInfinite(
    getKey,
    ([, f, page]) => getEvents({ ...filtersToQuery(f as FeedFilterState), page: page as number, page_size: 20 }),
    { revalidateFirstPage: false }
  )

  const events = data?.flatMap((p) => p.events) ?? []
  const isEmpty = !isLoading && !isValidating && events.length === 0
  const isLoadingMore = isValidating && size > (data?.length ?? 0)
  const hasError = !isLoading && data === undefined && !isValidating

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting && !isValidating) setSize((s) => s + 1) },
      { threshold: 0 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [isValidating, setSize])

  return (
    <div className="flex-1 overflow-y-auto px-5 py-3 bg-bg-page flex flex-col gap-2">
      <p className="text-[9px] uppercase tracking-widest text-accent-gold mb-1">Upcoming Events</p>

      {isLoading && Array.from({ length: 5 }).map((_, i) => (
        <SkeletonCard key={i} variant="feed" />
      ))}

      {hasError && (
        <p className="text-[10px] text-red-600 italic">
          Could not load events.{' '}
          <button onClick={() => setSize(1)} className="text-accent-gold underline">Retry</button>
        </p>
      )}

      {isEmpty && (
        <p className="text-[10px] text-text-muted italic">
          No events match your filters.
        </p>
      )}

      {events.map((evt) => (
        <EventCard
          key={evt.id}
          variant="feed"
          data={evt}
          onCardClick={onCardClick}
          onFeedback={onFeedback}
          onSave={onSave}
        />
      ))}

      {isLoadingMore && <p className="text-[9px] italic text-text-muted text-center py-1">Loading more…</p>}

      <div ref={sentinelRef} className="h-1" />
    </div>
  )
}
```

- [ ] **Step 9.3: Run tests — expect PASS**

```bash
npm test -- FeedSection
```
Expected: `2 passed`.

- [ ] **Step 9.4: Commit**

```bash
git add frontend/components/FeedSection.tsx frontend/components/__tests__/FeedSection.test.tsx
git commit -m "feat: add FeedSection with infinite scroll and filter integration"
```

---

## Task 10: useChat hook

**Files:**
- Create: `frontend/hooks/useChat.ts`
- Create: `frontend/hooks/__tests__/useChat.test.ts`

`useChat` manages one streaming chat session. It appends tokens to the last assistant message as they arrive.

- [ ] **Step 10.1: Write the failing test**

Create `frontend/hooks/__tests__/useChat.test.ts`:
```ts
import { renderHook, act } from '@testing-library/react'
import { useChat } from '@/hooks/useChat'

vi.mock('@/lib/api', () => ({
  postChat: vi.fn(),
}))
import { postChat } from '@/lib/api'
import type { ChatChunk } from '@/lib/types'

describe('useChat', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts with empty messages and not streaming', () => {
    const { result } = renderHook(() => useChat('sess_1'))
    expect(result.current.messages).toHaveLength(0)
    expect(result.current.isStreaming).toBe(false)
  })

  it('adds user message immediately on sendMessage', async () => {
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      onChunk({ type: 'done', token_usage: { input_tokens: 1, output_tokens: 1, estimated_cost_usd: 0 } })
    })
    const { result } = renderHook(() => useChat('sess_1'))
    await act(async () => { await result.current.sendMessage('hello') })
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: 'hello' })
  })

  it('assembles streamed tokens into one assistant message', async () => {
    const chunks: ChatChunk[] = [
      { type: 'token', content: 'Hello' },
      { type: 'token', content: ' world' },
      { type: 'done', token_usage: { input_tokens: 5, output_tokens: 2, estimated_cost_usd: 0 } },
    ]
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      for (const c of chunks) onChunk(c)
    })
    const { result } = renderHook(() => useChat('sess_1'))
    await act(async () => { await result.current.sendMessage('hi') })
    const assistantMsg = result.current.messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.content).toBe('Hello world')
  })

  it('records token usage from done chunk on last assistant message', async () => {
    const chunks: ChatChunk[] = [
      { type: 'token', content: 'Hi' },
      { type: 'done', token_usage: { input_tokens: 10, output_tokens: 3, estimated_cost_usd: 0.001 } },
    ]
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      for (const c of chunks) onChunk(c)
    })
    const { result } = renderHook(() => useChat('sess_1'))
    await act(async () => { await result.current.sendMessage('hi') })
    const assistantMsg = result.current.messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.tokenUsage?.input_tokens).toBe(10)
  })

  it('sets error on error chunk and stops streaming', async () => {
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      onChunk({ type: 'error', message: 'rate limited' })
    })
    const { result } = renderHook(() => useChat('sess_1'))
    await act(async () => { await result.current.sendMessage('hi') })
    expect(result.current.error).toBe('rate limited')
    expect(result.current.isStreaming).toBe(false)
  })
})
```

Run: `npm test -- useChat`
Expected: FAIL — module not found.

- [ ] **Step 10.2: Implement hooks/useChat.ts**

Create `frontend/hooks/useChat.ts`:
```ts
'use client'
import { useState, useCallback } from 'react'
import { postChat } from '@/lib/api'
import type { ChatTokenUsage } from '@/lib/types'

export interface LocalMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  toolName?: string
  tokenUsage?: ChatTokenUsage
  isStreaming?: boolean
}

interface ChatState {
  messages: LocalMessage[]
  isStreaming: boolean
  error: string | null
}

export function useChat(sessionId: string) {
  const [state, setState] = useState<ChatState>({
    messages: [], isStreaming: false, error: null,
  })

  const sendMessage = useCallback(async (text: string) => {
    const userMsg: LocalMessage = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    const assistantMsg: LocalMessage = { id: assistantId, role: 'assistant', content: '', isStreaming: true }

    setState((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
      error: null,
    }))

    await postChat({ message: text, session_id: sessionId }, (chunk) => {
      if (chunk.type === 'token') {
        setState((s) => ({
          ...s,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + chunk.content } : m
          ),
        }))
      } else if (chunk.type === 'tool_start') {
        const toolMsg: LocalMessage = {
          id: crypto.randomUUID(), role: 'tool', content: '', toolName: chunk.tool_name,
        }
        setState((s) => ({ ...s, messages: [...s.messages, toolMsg] }))
      } else if (chunk.type === 'done') {
        setState((s) => ({
          ...s,
          isStreaming: false,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false, tokenUsage: chunk.token_usage } : m
          ),
        }))
      } else if (chunk.type === 'error') {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: chunk.message,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false } : m
          ),
        }))
      }
    })
  }, [sessionId])

  return { ...state, sendMessage }
}
```

- [ ] **Step 10.3: Run tests — expect PASS**

```bash
npm test -- useChat
```
Expected: `5 passed`.

- [ ] **Step 10.4: Commit**

```bash
git add frontend/hooks/useChat.ts frontend/hooks/__tests__/useChat.test.ts
git commit -m "feat: add useChat hook for streaming chat session management"
```

---

## Task 11: ChatPanel component

**Files:**
- Create: `frontend/components/ChatPanel.tsx`
- Create: `frontend/components/__tests__/ChatPanel.test.tsx`

- [ ] **Step 11.1: Write the failing test**

Create `frontend/components/__tests__/ChatPanel.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ChatPanel from '@/components/ChatPanel'

vi.mock('@/lib/api', () => ({ postChat: vi.fn() }))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], isStreaming: false, error: null,
    sendMessage: vi.fn(),
  })),
}))
import { useChat } from '@/hooks/useChat'
import type { LocalMessage } from '@/hooks/useChat'

describe('ChatPanel', () => {
  it('renders header', () => {
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Chat Assistant')).toBeInTheDocument()
  })

  it('disables input while streaming', () => {
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: true, error: null, sendMessage: vi.fn(),
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByPlaceholderText(/Ask anything/)).toBeDisabled()
  })

  it('calls sendMessage on submit', async () => {
    const sendMessage = vi.fn()
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: false, error: null, sendMessage,
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    const input = screen.getByPlaceholderText(/Ask anything/)
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith('hello'))
  })

  it('renders assistant messages', () => {
    const messages: LocalMessage[] = [
      { id: '1', role: 'user', content: 'hello' },
      { id: '2', role: 'assistant', content: 'Hi there!' },
    ]
    vi.mocked(useChat).mockReturnValue({
      messages, isStreaming: false, error: null, sendMessage: vi.fn(),
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there!')).toBeInTheDocument()
  })
})
```

Run: `npm test -- ChatPanel`
Expected: FAIL — module not found.

- [ ] **Step 11.2: Implement ChatPanel.tsx**

Create `frontend/components/ChatPanel.tsx`:
```tsx
'use client'
import { useRef, useEffect, useState } from 'react'
import { useChat } from '@/hooks/useChat'
import type { Sentiment } from '@/lib/types'
import EventCard from './EventCard'

interface Props {
  sessionId: string
  model: string
  dailyCost: number
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

export default function ChatPanel({ sessionId, model, dailyCost, onCardClick, onFeedback, onSave }: Props) {
  const { messages, isStreaming, error, sendMessage } = useChat(sessionId)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleSubmit() {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    sendMessage(text)
  }

  return (
    <div className="flex flex-col w-[280px] flex-shrink-0 bg-bg-chat border-l border-border-warm">
      {/* Header */}
      <div className="px-3.5 py-2.5 border-b border-border-warm bg-accent-gold-light flex-shrink-0">
        <p className="font-serif font-bold text-xs text-text-primary">Chat Assistant</p>
        <p className="text-[9px] text-accent-gold mt-0.5">{model} · ${dailyCost.toFixed(4)} today</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-2.5 flex flex-col gap-2">
        {messages.map((msg) => {
          if (msg.role === 'tool') {
            return (
              <div key={msg.id} className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                <span className="text-[9px] italic text-accent-gold">{msg.toolName} running…</span>
              </div>
            )
          }
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="self-end max-w-[88%] rounded-lg rounded-br-sm bg-bg-surface px-2.5 py-1.5 text-[10px] italic text-text-primary">
                {msg.content}
              </div>
            )
          }
          return (
            <div key={msg.id} className="self-start max-w-[92%] rounded-lg rounded-bl-sm border border-border-warm bg-white px-2.5 py-1.5 text-[10px] text-text-primary">
              <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              {msg.isStreaming && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
              {msg.tokenUsage && (
                <p className="text-[8px] text-text-muted mt-1 text-right">
                  {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
                </p>
              )}
            </div>
          )
        })}
        {error && <p className="text-[9px] text-red-500 italic">{error}</p>}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-1.5 px-3 py-2 border-t border-border-warm">
        <input
          value={input}
          disabled={isStreaming}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask anything about events…"
          className="flex-1 text-[10px] border border-border-warm rounded px-2 py-1.5 bg-white disabled:bg-bg-surface"
        />
        <button
          aria-label="send"
          disabled={isStreaming}
          onClick={handleSubmit}
          className="bg-accent-gold text-bg-page rounded px-2.5 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          ↑
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 11.3: Run tests — expect PASS**

```bash
npm test -- ChatPanel
```
Expected: `4 passed`.

- [ ] **Step 11.4: Commit**

```bash
git add frontend/components/ChatPanel.tsx frontend/components/__tests__/ChatPanel.test.tsx
git commit -m "feat: add ChatPanel component with streaming message display"
```

---

## Task 12: EventDetailOverlay component

**Files:**
- Create: `frontend/components/EventDetailOverlay.tsx`
- Create: `frontend/components/__tests__/EventDetailOverlay.test.tsx`

The overlay renders as a React portal. `EventChat` reuses `useChat` with session `event_${eventId}`.

- [ ] **Step 12.1: Write the failing test**

Create `frontend/components/__tests__/EventDetailOverlay.test.tsx`:
```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import type { EventWithContext } from '@/lib/types'
import EventDetailOverlay from '@/components/EventDetailOverlay'

vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], isStreaming: false, error: null, sendMessage: vi.fn(),
  })),
}))

const mockEvent: EventWithContext = {
  id: 'evt_001', title: 'Jazz Night at Mojo Club', summary: 'Intimate trio set',
  start_datetime: '2026-06-09T20:00:00+02:00', end_datetime: null,
  venue_name: 'Mojo Club', venue_address: 'Reeperbahn 1',
  category: 'music', tags: ['jazz', 'live music'], price_min: 18, price_max: 24,
  is_free: false, currency: 'EUR',
  image_url: null, source_url: 'https://eventbrite.de/123',
  source: 'eventbrite', is_active: true,
  user_sentiment: null, user_comment: null, is_saved: false,
}

describe('EventDetailOverlay', () => {
  it('renders event title', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />,
      { container: document.body.appendChild(document.createElement('div')) }
    )
    expect(screen.getByText('Jazz Night at Mojo Club')).toBeInTheDocument()
  })

  it('renders venue and price', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    expect(screen.getByText('Mojo Club')).toBeInTheDocument()
    expect(screen.getByText(/€18/)).toBeInTheDocument()
  })

  it('renders AI justification callout', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    expect(screen.getByText(/Great match/)).toBeInTheDocument()
  })

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    fireEvent.click(screen.getByLabelText('Close overlay'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when Escape key pressed', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when backdrop clicked', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} />
    )
    fireEvent.click(screen.getByTestId('overlay-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
```

Run: `npm test -- EventDetailOverlay`
Expected: FAIL — module not found.

- [ ] **Step 12.2: Implement EventDetailOverlay.tsx**

Create `frontend/components/EventDetailOverlay.tsx`:
```tsx
'use client'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useChat } from '@/hooks/useChat'
import type { EventWithContext, Sentiment } from '@/lib/types'

interface Props {
  event: EventWithContext
  justification: string | null
  onClose: () => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
  })
}

function formatPrice(min: number | null, max: number | null, isFree: boolean) {
  if (isFree) return 'Free'
  if (min == null) return 'Price unknown'
  if (max != null && max !== min) return `€${min} – €${max}`
  return `€${min}`
}

function EventChat({ eventId }: { eventId: string }) {
  const { messages, isStreaming, error, sendMessage } = useChat(`event_${eventId}`)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleSubmit() {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    sendMessage(text)
  }

  return (
    <>
      <div className="flex flex-col gap-2 px-4 py-3">
        {messages.map((msg) => {
          if (msg.role === 'tool') {
            return (
              <div key={msg.id} className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                <span className="text-[9px] italic text-accent-gold">{msg.toolName} running…</span>
              </div>
            )
          }
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="self-end max-w-[85%] rounded-lg rounded-br-sm bg-bg-surface px-3 py-1.5 text-[10px] italic text-text-primary">
                {msg.content}
              </div>
            )
          }
          return (
            <div key={msg.id} className="self-start max-w-[90%] rounded-lg rounded-bl-sm border border-border-warm bg-white px-3 py-1.5 text-[10px] text-text-primary leading-relaxed">
              {msg.content}
              {msg.isStreaming && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
              {msg.tokenUsage && (
                <p className="text-[8px] text-text-muted mt-1 text-right">
                  {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
                </p>
              )}
            </div>
          )
        })}
        {error && <p className="text-[9px] text-red-500 italic">{error}</p>}
        <div ref={bottomRef} />
      </div>

      <div className="sticky bottom-0 flex gap-2 px-4 py-2.5 border-t border-border-warm bg-bg-chat">
        <input
          value={input}
          disabled={isStreaming}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask about this event, or leave a note for the agent…"
          className="flex-1 text-[10px] border border-border-warm rounded px-2.5 py-1.5 bg-white disabled:bg-bg-surface"
        />
        <button
          disabled={isStreaming}
          onClick={handleSubmit}
          className="bg-accent-gold text-bg-page rounded px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          ↑
        </button>
      </div>
      <p className="text-[8px] text-text-muted text-right px-4 pb-2 bg-bg-chat">
        Messages left here inform your taste profile
      </p>
    </>
  )
}

function OverlayContent({ event, justification, onClose, onFeedback, onSave }: Props) {
  const sentiment = event.user_sentiment

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      data-testid="overlay-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-text-primary/55 px-4"
      onClick={onClose}
    >
      <div
        className="relative bg-bg-page rounded-xl w-full max-w-lg max-h-[88vh] flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Hero */}
        <div
          className="relative h-36 flex-shrink-0 flex flex-col justify-between p-3"
          style={event.image_url
            ? { backgroundImage: `url(${event.image_url})`, backgroundSize: 'cover', backgroundPosition: 'center' }
            : { background: 'linear-gradient(160deg, #c4a882, #8a6040)' }
          }
        >
          <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/60" />
          <div className="relative z-10 flex justify-between">
            <div className="flex gap-2">
              <span className="rounded px-2 py-0.5 text-[9px] uppercase tracking-wider font-semibold bg-accent-gold text-bg-page">
                {event.category}
              </span>
              <a
                href={event.source_url}
                target="_blank"
                rel="noreferrer"
                className="rounded px-2 py-0.5 text-[9px] bg-black/30 text-white hover:bg-black/50"
                onClick={(e) => e.stopPropagation()}
              >
                {event.source} ↗
              </a>
            </div>
            <button
              aria-label="Close overlay"
              onClick={onClose}
              className="w-6 h-6 rounded-full bg-black/30 text-white flex items-center justify-center hover:bg-black/50 text-xs"
            >
              ✕
            </button>
          </div>
          <div className="relative z-10">
            <h2 className="font-serif font-bold text-lg text-white leading-tight">{event.title}</h2>
            <p className="text-[11px] text-white/80 mt-1">{formatDate(event.start_datetime)}</p>
          </div>
        </div>

        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 border-b border-border-warm bg-white flex-shrink-0">
          <div>
            <p className="text-[9px] uppercase tracking-wider text-accent-gold">Venue</p>
            <p className="text-[11px] font-semibold text-text-primary">{event.venue_name ?? 'TBC'}</p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-accent-gold">Price</p>
            <p className="text-[11px] font-semibold text-text-primary">{formatPrice(event.price_min, event.price_max, event.is_free)}</p>
          </div>
          {event.tags.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {event.tags.map((tag) => (
                <span key={tag} className="rounded bg-accent-gold-light text-accent-gold text-[9px] px-1.5 py-0.5">{tag}</span>
              ))}
            </div>
          )}
          <div className="ml-auto flex gap-1.5 items-center">
            <button
              aria-label="Like"
              onClick={() => onFeedback(event.id, 'like')}
              className={`rounded border px-2 py-1 text-xs ${sentiment === 'like' ? 'bg-accent-gold border-accent-gold text-bg-page' : 'bg-white border-border-warm'}`}
            >
              👍
            </button>
            <button
              aria-label="Dislike"
              onClick={() => onFeedback(event.id, 'dislike')}
              className={`rounded border px-2 py-1 text-xs ${sentiment === 'dislike' ? 'bg-text-secondary border-text-secondary text-bg-page' : 'bg-white border-border-warm'}`}
            >
              👎
            </button>
            <button
              onClick={() => onSave(event.id)}
              className="rounded bg-accent-gold text-bg-page text-[10px] font-semibold px-3 py-1"
            >
              {event.is_saved ? 'Saved ✓' : 'Save to Calendar'}
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {/* Description */}
          <div className="px-4 pt-4 pb-2 bg-bg-page">
            <p className="text-[9px] uppercase tracking-widest text-accent-gold mb-2">About this event</p>
            <p className="font-serif text-xs text-text-primary leading-7">
              {event.summary ?? 'No description available.'}
            </p>
          </div>

          {/* AI justification */}
          {justification && (
            <div className="mx-4 my-3 border-l-2 border-accent-gold rounded-r-lg bg-accent-gold-light px-3 py-2 text-[11px] italic text-text-primary leading-relaxed">
              ✦ "{justification}"
            </div>
          )}

          {/* Per-event chat */}
          <div className="border-t-2 border-border-warm mt-1 bg-bg-chat">
            <div className="px-4 pt-3 pb-1">
              <p className="text-[9px] uppercase tracking-widest text-accent-gold">Chat about this event</p>
              <p className="text-[9px] text-text-muted mt-0.5">Ask questions or leave a note for the agent</p>
            </div>
            <EventChat eventId={event.id} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function EventDetailOverlay(props: Props) {
  if (typeof document === 'undefined') return null
  return createPortal(<OverlayContent {...props} />, document.body)
}
```

- [ ] **Step 12.3: Run tests — expect PASS**

```bash
npm test -- EventDetailOverlay
```
Expected: `6 passed`.

- [ ] **Step 12.4: Commit**

```bash
git add frontend/components/EventDetailOverlay.tsx frontend/components/__tests__/EventDetailOverlay.test.tsx
git commit -m "feat: add EventDetailOverlay portal with per-event chat"
```

---

## Task 13: DashboardPage — wire everything together

**Files:**
- Modify: `frontend/app/page.tsx`

`DashboardPage` owns: `activeEventId` state, optimistic feedback/save mutation helpers, filter state, and SWR mutate callbacks passed down to all components.

- [ ] **Step 13.1: Write the failing test**

Create `frontend/components/__tests__/DashboardPage.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { SWRConfig } from 'swr'
import DashboardPage from '@/app/page'

vi.mock('@/lib/api', () => ({
  getDigest: vi.fn().mockResolvedValue({ date: '2026-06-08', picks: [], generated_at: '', is_cached: true }),
  getEvents: vi.fn().mockResolvedValue({ events: [], total: 0, page: 1, page_size: 20 }),
  refreshDigest: vi.fn(),
}))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({ messages: [], isStreaming: false, error: null, sendMessage: vi.fn() })),
}))

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
    {children}
  </SWRConfig>
)

describe('DashboardPage', () => {
  it('renders TopNav', () => {
    render(<DashboardPage />, { wrapper })
    expect(screen.getByText('Event Tracker')).toBeInTheDocument()
  })

  it('renders Today\'s Picks section header', async () => {
    render(<DashboardPage />, { wrapper })
    await screen.findByText("Today's Picks")
  })

  it('renders Chat Assistant panel', () => {
    render(<DashboardPage />, { wrapper })
    expect(screen.getByText('Chat Assistant')).toBeInTheDocument()
  })
})
```

Run: `npm test -- DashboardPage`
Expected: FAIL — module imports old page.

- [ ] **Step 13.2: Implement DashboardPage**

Replace `frontend/app/page.tsx`:
```tsx
'use client'
import { useState, useCallback } from 'react'
import useSWR from 'swr'
import { postFeedback, saveToCalendar, getSettings, getDigest, getEventDetail } from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import TopNav from '@/components/TopNav'
import DigestSection from '@/components/DigestSection'
import FeedFilters from '@/components/FeedFilters'
import type { FeedFilterState } from '@/components/FeedFilters'
import FeedSection from '@/components/FeedSection'
import ChatPanel from '@/components/ChatPanel'
import EventDetailOverlay from '@/components/EventDetailOverlay'

const DEFAULT_FILTERS: FeedFilterState = {
  category: null, datePreset: 'any', isFree: false, q: '',
}

export default function DashboardPage() {
  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS)

  // Read digest here too so we can look up justification when a digest card is clicked
  const { data: digest } = useSWR('/digest', getDigest)
  const { data: settings } = useSWR('/settings', getSettings)

  const handleFeedback = useCallback(async (eventId: string, sentiment: Sentiment) => {
    await postFeedback({ event_id: eventId, sentiment, comment: null })
  }, [])

  const handleSave = useCallback(async (eventId: string) => {
    await saveToCalendar(eventId)
  }, [])

  // All onCardClick callbacks use the same signature (id: string).
  // Justification is looked up from the digest cache if available.
  const handleCardClick = useCallback((eventId: string) => {
    setActiveEventId(eventId)
  }, [])

  const today = new Date().toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })
  const model = settings?.llm_model ?? 'gpt-4o-mini'
  const activeJustification = digest?.picks.find((p) => p.event.id === activeEventId)?.justification ?? null

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg-page">
      <TopNav active="dashboard" date={`Hamburg · ${today}`} />

      <div className="flex flex-1 overflow-hidden">
        {/* Left column */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <DigestSection
            onCardClick={handleCardClick}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
          <FeedFilters filters={filters} onChange={setFilters} />
          <FeedSection
            filters={filters}
            onCardClick={handleCardClick}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
        </div>

        {/* Chat panel */}
        <ChatPanel
          sessionId="dashboard"
          model={model}
          dailyCost={0}
          onCardClick={handleCardClick}
          onFeedback={handleFeedback}
          onSave={handleSave}
        />
      </div>

      {/* Event detail overlay */}
      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          justification={activeJustification}
          onClose={() => setActiveEventId(null)}
          onFeedback={handleFeedback}
          onSave={handleSave}
        />
      )}
    </div>
  )
}

// Fetches event detail via SWR then renders the overlay.
function EventDetailOverlayLoader({
  eventId, justification, onClose, onFeedback, onSave,
}: {
  eventId: string
  justification: string | null
  onClose: () => void
  onFeedback: (id: string, s: Sentiment) => void
  onSave: (id: string) => void
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
    />
  )
}
```

- [ ] **Step 13.3: Run all tests — expect PASS**

```bash
npm test
```
Expected: all tests pass.

- [ ] **Step 13.4: Commit**

```bash
git add frontend/app/page.tsx frontend/components/__tests__/DashboardPage.test.tsx
git commit -m "feat: implement DashboardPage wiring all dashboard components"
```

---

## Task 14: Manual smoke test

- [ ] **Step 14.1: Start dev server in mock mode**

In `frontend/`, ensure `.env.local` contains `NEXT_PUBLIC_MOCK_MODE=true`. If the file does not exist, create it:
```
NEXT_PUBLIC_MOCK_MODE=true
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USER_ID=local
```

Run:
```bash
npm run dev
```

Open `http://localhost:3000`.

- [ ] **Step 14.2: Verify key flows**

Check each of the following manually:

1. Today's Picks row shows 4 event cards in a horizontal scroll — each card has an image banner, title, venue, time, and justification text.
2. Scrollable feed shows events below the filter bar; filtering by "Music" narrows the list; "Free only" filters further.
3. Search input filters results as you type (after 300ms debounce).
4. Clicking a card title/image opens the EventDetailOverlay with hero, meta row, description, justification callout, and a chat input at the bottom.
5. Pressing Escape or clicking the backdrop closes the overlay.
6. Chat panel on the right renders "Chat Assistant" header; typing a message and pressing Enter triggers the mock streaming sequence (tokens appear word-by-word, tool indicator flashes briefly).
7. 👍/👎 buttons change to a filled gold/grey state on click.
8. "Save" button changes to "Saved ✓" on click.

- [ ] **Step 14.3: Final commit**

```bash
git add frontend/.env.local
git commit -m "chore: add .env.local for frontend mock mode"
```

> **Note:** add `frontend/.env.local` to `.gitignore` if it contains real secrets in the future. For mock mode it is safe to commit.
