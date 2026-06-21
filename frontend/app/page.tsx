'use client'
import { useMemo, useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { getCalendar, listAppointments } from '@/lib/api'
import type { Appointment, AppointmentsResponse, CalendarResponse } from '@/lib/types'
import { useAppShell } from '@/components/AppShell'
import WeekView from '@/components/calendar/WeekView'
import AppointmentModal from '@/components/calendar/appointmentModal/AppointmentModal'
import type { MakeInitial } from '@/components/calendar/appointmentModal/MakeAppointmentTab'
import { getWeekRange, type LaidOutItem } from '@/lib/calendarGrid'

function toKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function minutesToIso(day: string, minutes: number): string {
  const [y, m, d] = day.split('-').map(Number)
  const h = Math.floor(minutes / 60)
  const mm = minutes % 60
  return new Date(y, m - 1, d, h, mm).toISOString()
}

export default function CalendarPage() {
  const { openOverlay } = useAppShell()
  const { mutate } = useSWRConfig()
  const today = new Date()
  const todayKey = toKey(today)

  const [weekStart, setWeekStart] = useState<Date>(() => getWeekRange(new Date()).start)
  const [modal, setModal] = useState<{ mode: 'create' | 'edit'; initial: MakeInitial } | null>(null)

  const { start, end } = useMemo(() => {
    const r = getWeekRange(weekStart)
    return { start: toKey(r.start), end: toKey(new Date(r.end.getTime() - 1)) }
  }, [weekStart])

  const { data: appData, error: appError } = useSWR<AppointmentsResponse>(
    ['/appointments', start, end],
    () => listAppointments(start, end),
  )
  const { data: calData, error: calError } = useSWR<CalendarResponse>('/calendar', getCalendar)

  const appointments: Appointment[] = appData?.appointments ?? []
  const events = (calData?.entries ?? []).filter((entry) => {
    const k = toKey(new Date(entry.event.start_datetime))
    return k >= start && k <= end
  })

  const appointmentById = new Map(appointments.map(a => [a.id, a]))

  function shiftWeek(days: number) {
    const next = new Date(weekStart); next.setDate(next.getDate() + days)
    setWeekStart(next)
  }

  function onEmptyClick(dayKey: string, startMinutes: number) {
    setModal({
      mode: 'create',
      initial: {
        day: dayKey,
        start_at: minutesToIso(dayKey, startMinutes),
        end_at: null,
        title: '',
      },
    })
  }

  function onAllDayClick(dayKey: string) {
    setModal({
      mode: 'create',
      initial: { day: dayKey, start_at: null, end_at: null, title: '' },
    })
  }

  function onItemClick(item: LaidOutItem) {
    if (item.kind === 'event' || item.kind === 'recommendation') {
      openOverlay(item.id)
      return
    }
    const appt = appointmentById.get(item.id)
    if (!appt) return
    setModal({
      mode: 'edit',
      initial: {
        id: appt.id, day: appt.day, title: appt.title,
        start_at: appt.start_at, end_at: appt.end_at,
      },
    })
  }

  function onSaved() {
    mutate((key) => Array.isArray(key) && key[0] === '/appointments')
    mutate('/calendar')
  }

  return (
    <>
      {(appError || calError) && (
        <div className="flex flex-col gap-1 px-4 py-2 bg-bg-page border-b border-border">
          {appError && (
            <p data-testid="appointments-error" className="text-[10px] text-red-500">
              Couldn&apos;t load appointments.{' '}
              <button
                onClick={() => mutate((key) => Array.isArray(key) && key[0] === '/appointments')}
                className="underline"
              >Retry</button>
            </p>
          )}
          {calError && (
            <p data-testid="calendar-error" className="text-[10px] text-red-500">
              Couldn&apos;t load saved events.{' '}
              <button onClick={() => mutate('/calendar')} className="underline">Retry</button>
            </p>
          )}
        </div>
      )}
      <WeekView
        weekStart={weekStart}
        todayKey={todayKey}
        appointments={appointments}
        events={events}
        onPrev={() => shiftWeek(-7)}
        onNext={() => shiftWeek(7)}
        onToday={() => setWeekStart(getWeekRange(new Date()).start)}
        onEmptyClick={onEmptyClick}
        onItemClick={onItemClick}
        onAllDayClick={onAllDayClick}
      />
      {modal && (
        <AppointmentModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={onSaved}
        />
      )}
    </>
  )
}
