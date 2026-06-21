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
