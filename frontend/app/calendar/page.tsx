'use client'
import { useState, useEffect, useRef } from 'react'
import useSWR from 'swr'
import Link from 'next/link'
import { getCalendar, getEventDetail, postFeedback, saveToCalendar } from '@/lib/api'
import type { CalendarEntry, CalendarResponse, Sentiment } from '@/lib/types'
import { useSWRConfig } from 'swr'
import TopNav from '@/components/TopNav'
import EventDetailOverlay from '@/components/EventDetailOverlay'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']

function toDateKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function groupByDate(entries: CalendarEntry[]): Map<string, CalendarEntry[]> {
  const map = new Map<string, CalendarEntry[]>()
  for (const entry of entries) {
    const key = toDateKey(entry.event.start_datetime)
    const list = map.get(key) ?? []
    list.push(entry)
    map.set(key, list)
  }
  return map
}

function CalendarGrid({
  year, month, byDate, todayKey, onDayClick,
}: {
  year: number
  month: number
  byDate: Map<string, CalendarEntry[]>
  todayKey: string
  onDayClick: (eventId: string) => void
}) {
  const firstDayOfWeek = (new Date(year, month, 1).getDay() + 6) % 7 // Mon=0
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (number | null)[] = [
    ...Array<null>(firstDayOfWeek).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]

  return (
    <div className="grid grid-cols-7 gap-1">
      {DAYS.map((d) => (
        <div key={d} className="text-center text-[9px] text-text-muted py-1 uppercase tracking-wider">{d}</div>
      ))}
      {cells.map((day, i) => {
        if (day === null) return <div key={`pad-${i}`} />
        const dateKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
        const entries = byDate.get(dateKey)
        const hasEvents = !!entries
        const isToday = dateKey === todayKey
        return (
          <div
            key={day}
            data-testid={`day-${day}`}
            // Opens the first event on the day; multiple events per day are not yet supported
            onClick={() => hasEvents && onDayClick(entries![0].event.id)}
            className={[
              'flex flex-col items-center py-2 rounded',
              hasEvents ? 'cursor-pointer hover:bg-accent-gold-light' : 'cursor-default',
              isToday ? 'ring-1 ring-accent-gold' : '',
            ].join(' ')}
          >
            <span className={`text-xs leading-none ${isToday ? 'font-bold text-accent-gold' : 'text-text-primary'}`}>
              {day}
            </span>
            {hasEvents
              ? <span className="w-1.5 h-1.5 rounded-full bg-accent-gold mt-1" />
              : <span className="w-1.5 h-1.5 mt-1" />
            }
          </div>
        )
      })}
    </div>
  )
}

function EventDetailOverlayLoader({
  eventId, onClose,
}: {
  eventId: string
  onClose: () => void
}) {
  const { data: event } = useSWR(`/events/${eventId}`, () => getEventDetail(eventId))
  const { mutate } = useSWRConfig()

  async function handleSave(id: string) {
    await saveToCalendar(id)
    mutate(`/events/${id}`)
    mutate('/calendar')
  }

  async function handleFeedback(id: string, sentiment: Sentiment) {
    await postFeedback({ event_id: id, sentiment, comment: null })
  }

  if (!event) return null
  return (
    <EventDetailOverlay
      event={event}
      justification={null}
      onClose={onClose}
      onFeedback={handleFeedback}
      onSave={handleSave}
    />
  )
}

export default function CalendarPage() {
  const today = new Date()
  const todayKey = toDateKey(today.toISOString())
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const hasAutoJumped = useRef(false)

  const { data, error, isLoading } = useSWR<CalendarResponse>('/calendar', getCalendar)
  const entries = data?.entries ?? []
  const byDate = groupByDate(entries)

  // Auto-jump to earliest month with events on first load
  useEffect(() => {
    if (hasAutoJumped.current || !data || data.entries.length === 0) return
    const currentMonthHasEvents = data.entries.some((e) => {
      const d = new Date(e.event.start_datetime)
      return d.getFullYear() === year && d.getMonth() === month
    })
    if (!currentMonthHasEvents) {
      const earliest = data.entries.reduce<Date>((min, e) => {
        const d = new Date(e.event.start_datetime)
        return d < min ? d : min
      }, new Date(data.entries[0].event.start_datetime))
      setYear(earliest.getFullYear())
      setMonth(earliest.getMonth())
    }
    hasAutoJumped.current = true
  }, [data])

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11) }
    else setMonth(m => m - 1)
  }

  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0) }
    else setMonth(m => m + 1)
  }

  const currentMonthEntries = entries.filter((e) => {
    const d = new Date(e.event.start_datetime)
    return d.getFullYear() === year && d.getMonth() === month
  })

  const dateLabel = today.toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg-page">
      <TopNav active="calendar" date={`Hamburg · ${dateLabel}`} />

      <main className="flex-1 overflow-y-auto flex flex-col items-center py-8 px-4">
        <div className="w-full max-w-sm">
          {/* Month navigation */}
          <div className="flex items-center justify-between mb-6">
            <button
              onClick={prevMonth}
              aria-label="Previous month"
              className="rounded px-2 py-1 text-text-secondary hover:text-text-primary"
            >
              ‹
            </button>
            <h2 className="font-serif font-bold text-base text-text-primary">
              {MONTHS[month]} {year}
            </h2>
            <button
              onClick={nextMonth}
              aria-label="Next month"
              className="rounded px-2 py-1 text-text-secondary hover:text-text-primary"
            >
              ›
            </button>
          </div>

          {/* Calendar grid */}
          {isLoading && (
            <div className="text-center text-xs text-text-muted py-8">Loading…</div>
          )}
          {error && (
            <div className="text-center text-xs text-red-500 py-8">
              Failed to load calendar.{' '}
              <button onClick={() => window.location.reload()} className="underline">Retry</button>
            </div>
          )}
          {!isLoading && !error && (
            <CalendarGrid
              year={year}
              month={month}
              byDate={byDate}
              todayKey={todayKey}
              onDayClick={setActiveEventId}
            />
          )}

          {/* Empty state */}
          {!isLoading && !error && entries.length === 0 && (
            <p className="text-center text-xs text-text-muted mt-8">
              No saved events yet —{' '}
              <Link href="/" className="text-accent-gold underline">browse events to save some →</Link>
            </p>
          )}

          {/* Current month count hint */}
          {!isLoading && !error && entries.length > 0 && currentMonthEntries.length === 0 && (
            <p className="text-center text-[10px] text-text-muted mt-4">
              No saved events this month. Use ‹ › to navigate.
            </p>
          )}
        </div>
      </main>

      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          onClose={() => setActiveEventId(null)}
        />
      )}
    </div>
  )
}
