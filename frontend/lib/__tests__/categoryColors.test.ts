import { describe, expect, it } from 'vitest'
import { CATEGORY_BG, RECOMMENDATION_OPACITY, categoryBg } from '@/lib/categoryColors'

describe('categoryColors', () => {
  it('exports a hex for every EventCategory key', () => {
    const keys = [
      'concerts', 'party', 'comedy', 'theater', 'arts', 'literature',
      'film', 'family', 'food', 'sports', 'outdoor', 'other',
    ] as const
    for (const k of keys) {
      expect(CATEGORY_BG[k]).toMatch(/^#[0-9a-fA-F]{6}$/)
    }
  })

  it('categoryBg returns the matching hex for a known category', () => {
    expect(categoryBg('concerts')).toBe(CATEGORY_BG.concerts)
    expect(categoryBg('party')).toBe(CATEGORY_BG.party)
  })

  it('categoryBg falls back to the "other" swatch for null / undefined', () => {
    expect(categoryBg(null)).toBe(CATEGORY_BG.other)
    expect(categoryBg(undefined)).toBe(CATEGORY_BG.other)
  })

  it('exposes recommendation opacity as 0.55', () => {
    expect(RECOMMENDATION_OPACITY).toBe(0.55)
  })
})
