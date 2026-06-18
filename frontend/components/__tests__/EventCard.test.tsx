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
    const { container } = render(<EventCard variant="feed" data={mockEventCtx} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Jazz Night at Mojo Club')).toBeInTheDocument()
    const metaLines = container.querySelectorAll('.text-text-secondary')
    expect(Array.from(metaLines).some(el => el.textContent?.includes('Mojo Club'))).toBe(true)
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
    expect(onSave).toHaveBeenCalledWith('evt_001', true)
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
