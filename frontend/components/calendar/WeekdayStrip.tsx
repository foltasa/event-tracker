const SHORT = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function WeekdayStrip({
  weekStart, todayKey,
}: { weekStart: Date; todayKey: string }) {
  const days: Date[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart); d.setDate(weekStart.getDate() + i); return d
  })
  return (
    <div className="flex border-b border-border bg-bg-page">
      <div className="w-12 flex-shrink-0" />
      {days.map((d, i) => {
        const key = toKey(d)
        const isToday = key === todayKey
        const isWeekend = i >= 5
        return (
          <div
            key={key}
            className={`flex-1 py-2 text-center border-l border-border ${isWeekend ? 'bg-bg-surface' : ''}`}
          >
            <p className="text-[11px] uppercase tracking-wider text-text-muted">{SHORT[i]}</p>
            <p
              className={
                'mt-0.5 text-sm font-serif font-bold ' +
                (isToday
                  ? 'inline-flex items-center justify-center w-7 h-7 rounded-full bg-accent-gold text-bg-page'
                  : 'text-text-primary')
              }
            >
              {d.getDate()}
            </p>
          </div>
        )
      })}
    </div>
  )
}
