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
