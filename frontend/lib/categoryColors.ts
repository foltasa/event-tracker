import type { EventCategory } from '@/lib/types'

// Soft pastel backgrounds tuned to the warm-cream page (#faf7f2).
// Every value keeps near-black text (#1a1208) readable per the spec at
// docs/specs/2026-07-12-timetable-category-colors-design.md.
export const CATEGORY_BG: Record<EventCategory, string> = {
  concerts:   '#e0d3ea',
  party:      '#f4e2a8',
  comedy:     '#f5cfc6',
  theater:    '#e8ccd0',
  arts:       '#d3e0cf',
  literature: '#eee1c6',
  film:       '#cfd8e3',
  family:     '#b9dcd8',
  food:       '#edc9b3',
  sports:     '#cfe1d5',
  outdoor:    '#dbdfb8',
  other:      '#e0d8ca',
}

// Recommendation slots render the same category background at reduced opacity
// so the beige page bleeds through, replacing the old "Recommendation:" label.
export const RECOMMENDATION_OPACITY = 0.55

export function categoryBg(category: EventCategory | null | undefined): string {
  if (!category) return CATEGORY_BG.other
  return CATEGORY_BG[category] ?? CATEGORY_BG.other
}
