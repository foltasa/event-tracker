'use client'
import HourGutter from './HourGutter'
import WeekHeader from './WeekHeader'
import WeekdayStrip from './WeekdayStrip'
import DayColumn from './DayColumn'
import AllDayStrip from './AllDayStrip'
import { toGridItem, type GridItem, type LaidOutItem } from '@/lib/calendarGrid'
import type { Appointment, CalendarEntry } from '@/lib/types'
import { useEffect, useMemo, useRef } from 'react'
import { HOUR_PX } from './HourGutter'

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface Props {
  weekStart: Date
  todayKey: string
  appointments: Appointment[]
  events: CalendarEntry[]
  onPrev: () => void
  onNext: () => void
  onToday: () => void
  onEmptyClick: (dayKey: string, startMinutes: number) => void
  onItemClick: (item: LaidOutItem) => void
  onAllDayClick: (dayKey: string) => void
}

export default function WeekView({
  weekStart, todayKey, appointments, events,
  onPrev, onNext, onToday, onEmptyClick, onItemClick, onAllDayClick,
}: Props) {
  const items: GridItem[] = [
    ...appointments.map(a => toGridItem({ kind: 'appointment', raw: a })),
    ...events.map(e => toGridItem({ kind: 'event', raw: e })),
  ]

  const days: { key: string; date: Date }[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart); d.setDate(weekStart.getDate() + i)
    return { key: toKey(d), date: d }
  })

  const { allDayByDay, timedByDay } = useMemo(() => {
    const allDay = new Map<string, GridItem[]>()
    const timed = new Map<string, GridItem[]>()
    for (const it of items) {
      const bucket = it.startMinutes === null ? allDay : timed
      const arr = bucket.get(it.day) ?? []
      arr.push(it)
      bucket.set(it.day, arr)
    }
    return { allDayByDay: allDay, timedByDay: timed }
  }, [items])

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Scroll to 07:00 on mount so morning appointments are immediately visible
    if (scrollRef.current) scrollRef.current.scrollTop = 7 * HOUR_PX
  }, [])

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-bg-page">
      <WeekHeader weekStart={weekStart} onPrev={onPrev} onNext={onNext} onToday={onToday} />
      <WeekdayStrip weekStart={weekStart} todayKey={todayKey} />
      <AllDayStrip
        days={days}
        itemsByDay={allDayByDay}
        onItemClick={onItemClick}
        onAllDayClick={onAllDayClick}
      />
      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-auto">
        <div className="flex">
          <HourGutter />
          {days.map(({ key }) => (
            <DayColumn
              key={key}
              dayKey={key}
              items={timedByDay.get(key) ?? []}
              isToday={key === todayKey}
              onEmptyClick={onEmptyClick}
              onItemClick={onItemClick}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
