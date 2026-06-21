import { render, screen, fireEvent } from '@testing-library/react'
import type { EventWithContext } from '@/lib/types'
import EventDetailOverlay from '@/components/EventDetailOverlay'

vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], isStreaming: false, error: null, currentTool: null, sendMessage: vi.fn(),
  })),
}))

vi.mock('@/components/AppShell', () => ({
  useAppShell: vi.fn(() => ({
    isOptimisticallySaved: vi.fn(() => undefined),
    optimisticSentimentFor: vi.fn(() => undefined),
    openOverlay: vi.fn(),
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
  calendar_kind: null,
}

describe('EventDetailOverlay', () => {
  it('renders event title', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />,
      { container: document.body.appendChild(document.createElement('div')) }
    )
    expect(screen.getByText('Jazz Night at Mojo Club')).toBeInTheDocument()
  })

  it('renders venue and price', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByText('Mojo Club')).toBeInTheDocument()
    expect(screen.getByText(/€18/)).toBeInTheDocument()
  })

  it('renders AI justification callout', () => {
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByText(/Great match/)).toBeInTheDocument()
  })

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    fireEvent.click(screen.getByLabelText('Close overlay'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when Escape key pressed', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when backdrop clicked', () => {
    const onClose = vi.fn()
    render(
      <EventDetailOverlay event={mockEvent} justification="Great match." onClose={onClose} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    fireEvent.click(screen.getByTestId('overlay-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

const recommendationEvent: EventWithContext = {
  ...mockEvent, calendar_kind: 'recommendation', is_saved: true,
}

const savedEvent: EventWithContext = {
  ...mockEvent, calendar_kind: 'saved', is_saved: true,
}

const noEntryEvent: EventWithContext = {
  ...mockEvent, calendar_kind: null, is_saved: false,
}

describe('EventDetailOverlay action area', () => {
  it('shows only "Slot in" for noEntryEvent', () => {
    render(
      <EventDetailOverlay event={noEntryEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot in$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Slot out$/i })).not.toBeInTheDocument()
  })

  it('shows only "Slot Out" for savedEvent', () => {
    render(
      <EventDetailOverlay event={savedEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot Out$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Slot in$/i })).not.toBeInTheDocument()
  })

  it('shows both buttons for recommendationEvent', () => {
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /^Slot in$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Slot out$/i })).toBeInTheDocument()
  })

  it('calls onSlotIn(id) when slot-in clicked on a recommendation', () => {
    const onSlotIn = vi.fn()
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} onSlotIn={onSlotIn} />
    )
    fireEvent.click(screen.getByRole('button', { name: /^Slot in$/i }))
    expect(onSlotIn).toHaveBeenCalledWith('evt_001')
  })

  it('calls onSave(id, false) when slot-out clicked on a recommendation', () => {
    const onSave = vi.fn()
    render(
      <EventDetailOverlay event={recommendationEvent} justification={null}
        onClose={vi.fn()} onFeedback={vi.fn()} onSave={onSave} onSlotIn={vi.fn()} />
    )
    fireEvent.click(screen.getByRole('button', { name: /^Slot out$/i }))
    expect(onSave).toHaveBeenCalledWith('evt_001', false)
  })
})
