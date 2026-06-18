import { describe, expect, it } from 'vitest'
import {
  getWeekRange, layoutDayColumn, toGridItem,
  type GridItem,
} from '@/lib/calendarGrid'

describe('getWeekRange', () => {
  it('starts on Monday and ends Sunday 24:00', () => {
    // 2026-06-16 is a Tuesday
    const { start, end } = getWeekRange(new Date('2026-06-16T12:00:00Z'))
    expect(start.getDay()).toBe(1)   // Monday
    const endDay = new Date(end.getTime() - 1)  // Sunday 23:59:59.999
    expect(endDay.getDay()).toBe(0)  // Sunday
    expect(end.getHours()).toBe(0)   // midnight
    expect(end.getMinutes()).toBe(0)
  })

  it('uses local-time anchoring at midnight', () => {
    const { start } = getWeekRange(new Date('2026-06-16T12:00:00Z'))
    expect(start.getHours()).toBe(0)
    expect(start.getMinutes()).toBe(0)
  })
})

describe('toGridItem', () => {
  it('normalizes a timed appointment', () => {
    const out = toGridItem({
      kind: 'appointment',
      raw: {
        id: 'a1', title: 'Standup', day: '2026-06-16',
        start_at: '2026-06-16T09:00:00Z', end_at: '2026-06-16T09:30:00Z',
        created_at: '2026-06-16T00:00:00Z',
      },
    })
    expect(out.day).toBe('2026-06-16')
    expect(out.startMinutes).not.toBeNull()
    expect(out.endMinutes).not.toBeNull()
    expect(out.kind).toBe('appointment')
  })

  it('returns null minutes for an all-day appointment', () => {
    const out = toGridItem({
      kind: 'appointment',
      raw: {
        id: 'a1', title: 'Holiday', day: '2026-06-16',
        start_at: null, end_at: null,
        created_at: '2026-06-16T00:00:00Z',
      },
    })
    expect(out.startMinutes).toBeNull()
    expect(out.endMinutes).toBeNull()
  })
})

describe('layoutDayColumn', () => {
  const item = (id: string, s: number, e: number): GridItem => ({
    id, kind: 'appointment', title: id,
    day: '2026-06-16', startMinutes: s, endMinutes: e, raw: null as any,
  })

  it('gives non-overlapping items full width', () => {
    const laid = layoutDayColumn([item('a', 60, 120), item('b', 180, 240)])
    expect(laid.every(x => x.columnCount === 1 && x.column === 0)).toBe(true)
  })

  it('splits two overlapping items into 2 columns', () => {
    const laid = layoutDayColumn([item('a', 60, 180), item('b', 120, 240)])
    expect(laid.map(x => x.columnCount)).toEqual([2, 2])
    expect([...laid.map(x => x.column)].sort()).toEqual([0, 1])
  })

  it('groups three pairwise-overlapping items into 3 columns', () => {
    const laid = layoutDayColumn([
      item('a', 60, 240), item('b', 120, 300), item('c', 180, 360),
    ])
    expect(laid.every(x => x.columnCount === 3)).toBe(true)
    expect([...laid.map(x => x.column)].sort()).toEqual([0, 1, 2])
  })

  it('excludes all-day items', () => {
    const laid = layoutDayColumn([
      { ...item('a', 0, 0), startMinutes: null, endMinutes: null },
      item('b', 60, 120),
    ])
    expect(laid.length).toBe(1)
    expect(laid[0].id).toBe('b')
  })
})
