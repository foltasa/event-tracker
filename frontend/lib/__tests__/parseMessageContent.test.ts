import { parseMessageContent } from '@/lib/parseMessageContent'

const UUID = '550e8400-e29b-41d4-a716-446655440000'

describe('parseMessageContent', () => {
  it('returns a single text segment when no markers present', () => {
    const result = parseMessageContent('Hello world')
    expect(result).toEqual([{ type: 'text', value: 'Hello world' }])
  })

  it('returns a single text segment for empty string', () => {
    expect(parseMessageContent('')).toEqual([{ type: 'text', value: '' }])
  })

  it('parses a single event marker into an event segment', () => {
    const result = parseMessageContent(`[event:${UUID}]`)
    expect(result).toEqual([{ type: 'event', id: UUID }])
  })

  it('splits text around a marker correctly', () => {
    const result = parseMessageContent(`Check out [event:${UUID}] tonight!`)
    expect(result).toEqual([
      { type: 'text', value: 'Check out ' },
      { type: 'event', id: UUID },
      { type: 'text', value: ' tonight!' },
    ])
  })

  it('handles multiple markers', () => {
    const UUID2 = '660e8400-e29b-41d4-a716-446655440001'
    const result = parseMessageContent(`A [event:${UUID}] and B [event:${UUID2}]`)
    expect(result).toEqual([
      { type: 'text', value: 'A ' },
      { type: 'event', id: UUID },
      { type: 'text', value: ' and B ' },
      { type: 'event', id: UUID2 },
    ])
  })

  it('does not match malformed markers with non-UUID content', () => {
    const result = parseMessageContent('[event:not-a-uuid]')
    expect(result).toEqual([{ type: 'text', value: '[event:not-a-uuid]' }])
  })

  it('is case-insensitive for hex digits in UUID', () => {
    const upperUUID = UUID.toUpperCase()
    const result = parseMessageContent(`[event:${upperUUID}]`)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('event')
  })
})
