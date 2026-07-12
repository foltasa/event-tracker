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
