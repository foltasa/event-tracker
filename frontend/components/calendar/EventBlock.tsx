import { HOUR_PX } from './HourGutter'
import type { LaidOutItem } from '@/lib/calendarGrid'

function fmtTime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
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
  const borderColor = item.kind === 'event' ? 'border-accent-gold' : 'border-text-secondary'
  return (
    <button
      data-testid={`event-block-${item.id}`}
      data-kind={item.kind}
      onClick={(e) => { e.stopPropagation(); onClick(item) }}
      style={{
        top: startPx, height: heightPx,
        left: `calc(${leftPct}% + 2px)`, width: `calc(${widthPct}% - 4px)`,
      }}
      className={`absolute z-10 text-left rounded-md bg-white border border-border border-l-[3px] ${borderColor} px-2 py-1 overflow-hidden hover:shadow-sm`}
    >
      <p className="text-[11px] font-semibold text-text-primary truncate">{item.title}</p>
      <p className="text-[10px] text-text-muted">
        {fmtTime(item.startMinutes!)}{item.endMinutes != null ? ` – ${fmtTime(item.endMinutes)}` : ''}
      </p>
    </button>
  )
}
