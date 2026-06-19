const HOURS = Array.from({ length: 24 }, (_, i) => i)
export const HOUR_PX = 48

export default function HourGutter() {
  return (
    <div className="flex flex-col w-12 flex-shrink-0 border-r border-border">
      {HOURS.map((h) => (
        <div
          key={h}
          style={{ height: HOUR_PX }}
          className="text-[11px] text-text-muted text-right pr-2 -mt-1.5"
        >
          {String(h).padStart(2, '0')}
        </div>
      ))}
    </div>
  )
}
