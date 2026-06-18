import { render, screen } from '@testing-library/react'
import { SWRConfig } from 'swr'
import DashboardPage from '@/app/page'

vi.mock('@/lib/api', () => ({
  getDigest: vi.fn().mockResolvedValue({ date: '2026-06-08', picks: [], generated_at: '', is_cached: true }),
  getEvents: vi.fn().mockResolvedValue({ events: [], total: 0, page: 1, page_size: 20 }),
  refreshDigest: vi.fn(),
  postFeedback: vi.fn(),
  saveToCalendar: vi.fn(),
  getSettings: vi.fn().mockResolvedValue({ llm_model: 'gpt-4o-mini', user_id: 'local' }),
}))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({ messages: [], isStreaming: false, error: null, sendMessage: vi.fn() })),
}))
vi.mock('@/components/AppShell', () => ({
  useAppShell: vi.fn(() => ({
    openOverlay: vi.fn(),
    handleSave: vi.fn(),
    handleFeedback: vi.fn(),
    isOptimisticallySaved: vi.fn(() => undefined),
    optimisticSentimentFor: vi.fn(() => undefined),
  })),
}))

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
    {children}
  </SWRConfig>
)

describe('DashboardPage', () => {
  it("renders Today's Picks section header", async () => {
    render(<DashboardPage />, { wrapper })
    await screen.findByText("Today's Picks")
  })

  it('renders Upcoming Events feed header', async () => {
    render(<DashboardPage />, { wrapper })
    await screen.findByText('Upcoming Events')
  })
})
