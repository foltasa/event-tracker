import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import EventChip from '@/components/EventChip'

vi.mock('swr', () => ({
  default: vi.fn(),
  useSWRConfig: () => ({ mutate: vi.fn() }),
}))
vi.mock('@/lib/api', () => ({
  getEventDetail: vi.fn(),
  saveToCalendar: vi.fn(),
}))

import useSWR from 'swr'
import { saveToCalendar } from '@/lib/api'

const mockEvent = {
  id: 'evt-1', title: 'Tango Festival', summary: null,
  start_datetime: '2026-06-20T18:00:00Z', end_datetime: null,
  venue_name: 'Fabrik', venue_address: null, category: 'music' as const,
  tags: [], price_min: null, price_max: null, is_free: false, currency: 'EUR',
  image_url: null, source_url: 'https://example.com', source: 'test',
  is_active: true, user_sentiment: null, user_comment: null, is_saved: false,
}

describe('EventChip', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders a loading skeleton when event data is not yet available', () => {
    vi.mocked(useSWR).mockReturnValue({ data: undefined, error: undefined, mutate: vi.fn() } as any)
    const { container } = render(<EventChip eventId="evt-1" />)
    expect(container.querySelector('[data-testid="chip-skeleton"]')).toBeInTheDocument()
  })

  it('renders fallback text when fetch errors', () => {
    vi.mocked(useSWR).mockReturnValue({ data: undefined, error: new Error('404'), mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByText('[event not found]')).toBeInTheDocument()
  })

  it('renders event title and venue when loaded', () => {
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByText('Tango Festival')).toBeInTheDocument()
    expect(screen.getByText(/Fabrik/)).toBeInTheDocument()
  })

  it('shows Slot in button when is_saved is false', () => {
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /slot in/i })).toBeInTheDocument()
    expect(screen.queryByText(/slot out/i)).not.toBeInTheDocument()
  })

  it('shows Slot Out when is_saved is true', () => {
    vi.mocked(useSWR).mockReturnValue({ data: { ...mockEvent, is_saved: true }, error: undefined, mutate: vi.fn() } as any)
    render(<EventChip eventId="evt-1" />)
    expect(screen.getByRole('button', { name: /slot out/i })).toBeInTheDocument()
  })

  it('calls saveToCalendar with the event id on Slot in click', async () => {
    const mutate = vi.fn()
    vi.mocked(useSWR).mockReturnValue({ data: mockEvent, error: undefined, mutate } as any)
    vi.mocked(saveToCalendar).mockResolvedValue({} as any)
    render(<EventChip eventId="evt-1" />)
    fireEvent.click(screen.getByRole('button', { name: /slot in/i }))
    await waitFor(() => expect(saveToCalendar).toHaveBeenCalledWith('evt-1'))
  })
})
