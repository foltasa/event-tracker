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
