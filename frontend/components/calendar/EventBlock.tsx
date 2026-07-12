import { HOUR_PX } from './HourGutter'
import type { LaidOutItem } from '@/lib/calendarGrid'
import type { CalendarEntry } from '@/lib/types'
import { categoryBg, RECOMMENDATION_OPACITY } from '@/lib/categoryColors'

function fmtTime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function backgroundFor(item: LaidOutItem): string {
  if (item.kind === 'appointment') return '#ffffff'
  const entry = item.raw as CalendarEntry
  return categoryBg(entry.event?.category)
}

export default function EventBlock({
  item, onClick,
}: {
  item: LaidOutItem
  onClick: (item: LaidOutItem) => void
}) {
  const startPx = (item.startMinutes! / 60) * HOUR_PX
  const endMinutes = item.endMinutes ?? 24 * 60
  const heightPx = Math.max(20, ((endMinutes - item.startMinutes!) / 60) * HOUR_PX)
  const widthPct = 100 / item.columnCount
  const leftPct = item.column * widthPct

  const isRec = item.kind === 'recommendation'
  const borderClasses =
    item.kind === 'appointment'
      ? 'border border-border border-l-[3px] border-text-secondary'
      : 'border border-border border-l-[3px] border-accent-gold'

  return (
    <button
      data-testid={`event-block-${item.id}`}
      data-kind={item.kind}
      onClick={(e) => { e.stopPropagation(); onClick(item) }}
      style={{
        top: startPx, height: heightPx,
        left: `calc(${leftPct}% + 2px)`, width: `calc(${widthPct}% - 4px)`,
        background: backgroundFor(item),
        opacity: isRec ? RECOMMENDATION_OPACITY : undefined,
      }}
      className={`absolute z-10 text-left rounded-md ${borderClasses} px-2 py-1 overflow-hidden hover:shadow-sm cursor-pointer`}
    >
      <p className="text-[11px] font-semibold truncate text-text-primary">{item.title}</p>
      <p className="text-[10px] text-text-primary">
        {fmtTime(item.startMinutes!)}{item.endMinutes != null ? ` – ${fmtTime(item.endMinutes)}` : ''}
      </p>
    </button>
  )
}
