import { saveToCalendar } from '@/lib/api'

const mockEntry = {
  id: 'sav-1',
  event: { id: 'evt-1', title: 'Test', summary: null, start_datetime: '2026-06-20T18:00:00Z',
    end_datetime: null, venue_name: null, venue_address: null, category: 'music' as const,
    tags: [], price_min: null, price_max: null, is_free: true, currency: 'EUR',
    image_url: null, source_url: 'https://example.com', source: 'test', is_active: true },
  saved_at: '2026-06-16T10:00:00Z',
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
