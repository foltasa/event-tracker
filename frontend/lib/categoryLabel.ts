import type { EventCategory } from './types'

// German labels for user-facing category display. The enum stays the source
// of truth for filtering and persistence; this map is presentation-only.
const _LABELS: Record<EventCategory, string> = {
  concerts: 'Konzerte',
  party: 'Party',
  comedy: 'Comedy',
  theater: 'Theater',
  arts: 'Kunst',
  literature: 'Literatur',
  film: 'Film',
  family: 'Familie',
  food: 'Kulinarik',
  sports: 'Sport',
  outdoor: 'Outdoor',
  other: 'Sonstiges',
}

export function categoryLabel(category: EventCategory): string {
  return _LABELS[category] ?? category
}
