import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import SettingsPage from '@/app/settings/page'

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
  return {
    ...actual,
    getProfile: vi.fn(async () => ({
      city: 'Hamburg', interest_tags: [], about_me: null, taste_summary: null,
      settings: {
        tool_toggles: {}, llm_provider: 'openai', llm_model: null,
        auto_recommendations_enabled: true,
      },
    })),
    updateProfileSettings: vi.fn(async (b: { auto_recommendations_enabled: boolean }) => ({
      city: 'Hamburg', interest_tags: [], about_me: null, taste_summary: null,
      settings: {
        tool_toggles: {}, llm_provider: 'openai', llm_model: null,
        auto_recommendations_enabled: b.auto_recommendations_enabled,
      },
    })),
  }
})

function wrap(node: React.ReactNode) {
  return <SWRConfig value={{ provider: () => new Map() }}>{node}</SWRConfig>
}

describe('SettingsPage', () => {
  it('renders the auto-recommendations toggle', async () => {
    render(wrap(<SettingsPage />))
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /Add recommendations/i })).toBeInTheDocument()
    })
  })

  it('toggle is checked when auto_recommendations_enabled=true', async () => {
    render(wrap(<SettingsPage />))
    const toggle = await screen.findByRole('checkbox', { name: /Add recommendations/i })
    expect(toggle).toBeChecked()
  })

  it('clicking the toggle calls updateProfileSettings with the new value', async () => {
    const { updateProfileSettings } = await import('@/lib/api')
    render(wrap(<SettingsPage />))
    const toggle = await screen.findByRole('checkbox', { name: /Add recommendations/i })
    fireEvent.click(toggle)
    await waitFor(() => {
      expect(updateProfileSettings).toHaveBeenCalledWith({ auto_recommendations_enabled: false })
    })
  })
})
