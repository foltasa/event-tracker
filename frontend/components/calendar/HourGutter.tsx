const HOURS = Array.from({ length: 24 }, (_, i) => i)
export const HOUR_PX = 48

export default function HourGutter() {
  return (
    <div className="flex flex-col w-12 flex-shrink-0 border-r border-border">
      {HOURS.map((h) => (
        <div
          key={h}
          style={{ height: HOUR_PX }}
          className="relative"
        >
          {/* Label is absolutely positioned so it can sit visually above the
              hour line without shrinking the row's contribution to the flex
              container height. Previously a negative margin was used, which
              compounded across 24 rows and compressed the whole gutter by
              24 * 6 = 144 px (three hours), misaligning it with the grid. */}
          <span className="absolute right-2 -top-1.5 text-[11px] text-text-muted">
            {String(h).padStart(2, '0')}
          </span>
        </div>
      ))}
    </div>
  )
}
