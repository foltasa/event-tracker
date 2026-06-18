const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function label(weekStart: Date): string {
  const end = new Date(weekStart); end.setDate(weekStart.getDate() + 6)
  if (weekStart.getMonth() === end.getMonth()) {
    return `${MONTHS[weekStart.getMonth()]} ${weekStart.getFullYear()}`
  }
  return `${MONTHS[weekStart.getMonth()]} – ${MONTHS[end.getMonth()]} ${end.getFullYear()}`
}

export default function WeekHeader({
  weekStart, onPrev, onNext, onToday,
}: {
  weekStart: Date
  onPrev: () => void
  onNext: () => void
  onToday: () => void
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-bg-page">
      <div className="flex items-center gap-2">
        <button
          onClick={onPrev}
          aria-label="Previous week"
          className="rounded px-2 py-1 text-text-secondary hover:text-text-primary text-lg"
        >‹</button>
        <button
          onClick={onNext}
          aria-label="Next week"
          className="rounded px-2 py-1 text-text-secondary hover:text-text-primary text-lg"
        >›</button>
        <button
          onClick={onToday}
          aria-label="Go to today"
          className="ml-2 text-[11px] uppercase tracking-wider text-accent-gold hover:underline"
        >Today</button>
      </div>
      <h2 className="font-serif font-bold text-base text-text-primary">{label(weekStart)}</h2>
      <div className="w-24" />
    </div>
  )
}
