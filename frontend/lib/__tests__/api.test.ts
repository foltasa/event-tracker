import {
  saveToCalendar,
  createAppointment, deleteAppointment, listAppointments,
  recommendAppointment, updateAppointment,
} from '@/lib/api'

const mockEntry = {
  id: 'sav-1',
  event: { id: 'evt-1', title: 'Test', summary: null, start_datetime: '2026-06-20T18:00:00Z',
    end_datetime: null, venue_name: null, venue_address: null, category: 'music' as const,
    tags: [], price_min: null, price_max: null, is_free: true, currency: 'EUR',
    image_url: null, source_url: 'https://example.com', source: 'test', is_active: true },
  saved_at: '2026-06-16T10:00:00Z',
}

const mockApp = {
  id: 'app-1', title: 'X', day: '2026-06-16',
  start_at: null, end_at: null, created_at: '2026-06-16T10:00:00Z',
}

describe('saveToCalendar', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockEntry,
    } as Response)
  })

  it('POSTs to /calendar (not /calendar/{id})', async () => {
    await saveToCalendar('evt-1')
    const [url] = vi.mocked(global.fetch).mock.calls[0]
    expect(url).toMatch(/\/calendar$/)
  })

  it('sends event_id in the request body', async () => {
    await saveToCalendar('evt-1')
    const [, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(JSON.parse(init!.body as string)).toEqual({ event_id: 'evt-1' })
  })
})

describe('appointments API', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ appointments: [mockApp] }),
    } as Response)
  })

  it('listAppointments GETs /appointments with from/to', async () => {
    await listAppointments('2026-06-01', '2026-06-30')
    const [url] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\?from=2026-06-01&to=2026-06-30$/)
  })

  it('createAppointment POSTs JSON body', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => mockApp,
    } as Response)
    await createAppointment({ title: 'X', day: '2026-06-16', start_at: null, end_at: null })
    const [, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(init!.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual({
      title: 'X', day: '2026-06-16', start_at: null, end_at: null,
    })
  })

  it('updateAppointment PATCHes /appointments/{id}', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => mockApp,
    } as Response)
    await updateAppointment('app-1', { title: 'Renamed' })
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\/app-1$/)
    expect(init!.method).toBe('PATCH')
  })

  it('deleteAppointment DELETEs /appointments/{id}', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
    } as Response)
    await deleteAppointment('app-1')
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/appointments\/app-1$/)
    expect(init!.method).toBe('DELETE')
  })

  it('recommendAppointment POSTs to /appointments/recommend', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true, json: async () => ({ message: 'Currently not implemented' }),
    } as Response)
    const out = await recommendAppointment({
      day: '2026-06-16', start_at: null, end_at: null, message: 'hi',
    })
    expect(out).toEqual({ message: 'Currently not implemented' })
  })
})

describe('slotInRecommendation', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...mockEntry, kind: 'saved' }),
    } as Response)
  })

  it('POSTs /calendar/{id}/slot-in', async () => {
    const { slotInRecommendation } = await import('@/lib/api')
    await slotInRecommendation('evt-1')
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/calendar\/evt-1\/slot-in$/)
    expect(init?.method).toBe('POST')
  })
})

describe('updateProfileSettings', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        city: 'Hamburg', interest_tags: [], about_me: null, taste_summary: null,
        settings: { tool_toggles: {}, llm_provider: 'openai', llm_model: null,
                    auto_recommendations_enabled: false },
      }),
    } as Response)
  })

  it('PUTs /profile/settings with the partial body', async () => {
    const { updateProfileSettings } = await import('@/lib/api')
    await updateProfileSettings({ auto_recommendations_enabled: false })
    const [url, init] = vi.mocked(global.fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/profile\/settings$/)
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init!.body as string)).toEqual({ auto_recommendations_enabled: false })
  })
})
