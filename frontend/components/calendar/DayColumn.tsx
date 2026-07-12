'use client'
import { useRef } from 'react'
import EventBlock from './EventBlock'
import NowLine from './NowLine'
import { HOUR_PX } from './HourGutter'
import { layoutDayColumn, type GridItem, type LaidOutItem } from '@/lib/calendarGrid'

const GRID_PX = 24 * HOUR_PX
const SNAP_MIN = 30

export default function DayColumn({
  dayKey, items, isToday, onEmptyClick, onItemClick,
}: {
  dayKey: string
  items: GridItem[]
  isToday: boolean
  onEmptyClick: (dayKey: string, startMinutes: number) => void
  onItemClick: (item: LaidOutItem) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const timed = layoutDayColumn(items)

  function handleBackgroundClick(e: React.MouseEvent) {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    const y = e.clientY - rect.top
    const rawMinutes = Math.max(0, Math.min(24 * 60 - SNAP_MIN, (y / HOUR_PX) * 60))
    const snapped = Math.round(rawMinutes / SNAP_MIN) * SNAP_MIN
    onEmptyClick(dayKey, snapped)
  }

  return (
    <div
      ref={ref}
      onClick={handleBackgroundClick}
      className="flex-1 relative border-l border-border min-w-0 cursor-pointer"
      style={{
        height: GRID_PX,
        backgroundImage:
          'repeating-linear-gradient(to bottom, transparent 0, transparent 47px, rgb(232,224,212) 47px, rgb(232,224,212) 48px)',
      }}
    >
      {isToday && <NowLine />}
      {timed.map((it) => (
        <EventBlock key={it.id} item={it} onClick={onItemClick} />
      ))}
    </div>
  )
}
