'use client'
import type { EventCategory } from '@/lib/types'

export type DatePreset = 'any' | 'today' | 'this-week' | 'this-weekend'

export interface FeedFilterState {
  category: EventCategory | null
  datePreset: DatePreset
  isFree: boolean
  q: string
}

const CATEGORIES: EventCategory[] = ['music', 'arts', 'food', 'sports', 'tech', 'outdoor', 'film', 'theater', 'family', 'other']

interface Props {
  filters: FeedFilterState
  onChange: (f: FeedFilterState) => void
}

export default function FeedFilters({ filters, onChange }: Props) {
  function chip(label: string, active: boolean, onClick: () => void) {
    return (
      <button
        key={label}
        onClick={onClick}
        className={`rounded px-2 py-0.5 text-[10px] cursor-pointer ${active ? 'bg-accent-gold text-bg-page font-semibold' : 'border border-border text-text-secondary hover:bg-accent-gold-light'}`}
      >
        {label}
      </button>
    )
  }

  return (
    <div className="sticky flex flex-wrap items-center gap-1.5 px-5 py-2 border-b border-border bg-bg-page">
      <span className="text-[9px] uppercase tracking-widest text-accent-gold mr-1">Filter:</span>

      {chip('All', filters.category === null, () => onChange({ ...filters, category: null }))}
      {CATEGORIES.map((cat) =>
        chip(cat.charAt(0).toUpperCase() + cat.slice(1), filters.category === cat, () =>
          onChange({ ...filters, category: cat })
        )
      )}

      {chip('Free only', filters.isFree, () => onChange({ ...filters, isFree: !filters.isFree }))}

      <select
        value={filters.datePreset}
        onChange={(e) => onChange({ ...filters, datePreset: e.target.value as DatePreset })}
        className="ml-1 text-[10px] border border-border rounded px-1.5 py-0.5 bg-white text-text-secondary"
      >
        <option value="any">Any time</option>
        <option value="today">Today</option>
        <option value="this-week">This week</option>
        <option value="this-weekend">This weekend</option>
      </select>

      <input
        type="text"
        value={filters.q}
        onChange={(e) => onChange({ ...filters, q: e.target.value })}
        placeholder="🔍 Search events..."
        className="ml-auto text-[10px] border border-border rounded px-2 py-0.5 bg-white text-text-primary w-32"
      />
    </div>
  )
}
