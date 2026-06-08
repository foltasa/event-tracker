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
