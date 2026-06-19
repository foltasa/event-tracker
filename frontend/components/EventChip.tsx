'use client'
import useSWR from 'swr'
import { useState } from 'react'
import { getEventDetail, removeFromCalendar, saveToCalendar } from '@/lib/api'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'short', day: 'numeric', month: 'short',
  })
}

export default function EventChip({ eventId }: { eventId: string }) {
  const { data: event, error, mutate } = useSWR(
    `/events/${eventId}`,
    () => getEventDetail(eventId),
  )
  const [saveError, setSaveError] = useState<string | null>(null)

  if (error) return <span className="text-[9px] text-text-muted">[event not found]</span>
  if (!event) {
    return (
      <span
        data-testid="chip-skeleton"
        className="inline-block h-5 w-48 rounded bg-bg-surface animate-pulse"
      />
    )
  }

  async function handleToggle() {
    if (!event) return
    const nextSaved = !event.is_saved
    setSaveError(null)
    mutate({ ...event, is_saved: nextSaved }, false)
    try {
      if (nextSaved) await saveToCalendar(eventId)
      else            await removeFromCalendar(eventId)
      mutate()
    } catch {
      mutate({ ...event, is_saved: !nextSaved }, false)
      setSaveError(nextSaved ? 'Failed to save — try again' : 'Failed to remove — try again')
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap my-0.5">
      <span className="inline-flex items-center gap-1.5 bg-accent-gold-light border border-accent-gold/30 rounded px-2 py-1 text-[9px] text-text-primary">
        <span className="uppercase tracking-wider font-semibold text-accent-gold">{event.category}</span>
        <span className="font-semibold">{event.title}</span>
        <span className="text-text-muted">·</span>
        <span className="text-text-muted">{formatDate(event.start_datetime)}</span>
        {event.venue_name && (
          <>
            <span className="text-text-muted">·</span>
            <span className="text-text-muted">{event.venue_name}</span>
          </>
        )}
        <button
          onClick={handleToggle}
          className={`ml-1 rounded px-2 py-0.5 text-[8px] font-semibold ${
            event.is_saved
              ? 'bg-accent-gold-light text-accent-gold'
              : 'bg-accent-gold text-bg-page'
          }`}
        >
          {event.is_saved ? 'Slot Out' : 'Slot in'}
        </button>
      </span>
      {saveError && <span className="text-[8px] text-red-500">{saveError}</span>}
    </span>
  )
}
