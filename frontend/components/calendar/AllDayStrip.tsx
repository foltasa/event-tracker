'use client'
import type { GridItem, LaidOutItem } from '@/lib/calendarGrid'

interface Props {
  days: { key: string }[]
  itemsByDay: Map<string, GridItem[]>
  onItemClick: (item: LaidOutItem) => void
  onAllDayClick: (dayKey: string) => void
}

// Shared all-day strip that spans the whole week. It sits outside the vertical
// scroll area so its height doesn't push the timed grid down relative to the
// hour gutter — that misalignment is what caused hour labels to drift.
export default function AllDayStrip({ days, itemsByDay, onItemClick, onAllDayClick }: Props) {
  return (
    <div className="flex border-b border-border bg-bg-surface">
      <div className="w-12 flex-shrink-0 border-r border-border" />
      {days.map(({ key }) => {
        const items = itemsByDay.get(key) ?? []
        return (
          <div
            key={key}
            role="button"
            tabIndex={0}
            onClick={() => onAllDayClick(key)}
            aria-label="Add all-day appointment"
            className="flex-1 min-h-[24px] flex flex-col gap-0.5 p-0.5 border-l border-border cursor-pointer text-left"
          >
            {items.map((it) => (
              <button
                key={it.id}
                data-testid={`allday-block-${it.id}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onItemClick({ ...it, column: 0, columnCount: 1 })
                }}
                className="text-[10px] truncate rounded bg-white px-1 py-0.5 border-l-[3px] border-text-secondary text-left"
              >
                {it.title}
              </button>
            ))}
          </div>
        )
      })}
    </div>
  )
}
