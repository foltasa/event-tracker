'use client'
import useSWR from 'swr'
import { useState } from 'react'
import { getEventDetail, saveToCalendar } from '@/lib/api'

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

  async function handleSave() {
    if (!event) return
    setSaveError(null)
    mutate({ ...event, is_saved: true }, false)
    try {
      await saveToCalendar(eventId)
      mutate()
    } catch {
      mutate({ ...event, is_saved: false }, false)
      setSaveError('Failed to save — try again')
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
          onClick={handleSave}
          disabled={event.is_saved}
          className="ml-1 rounded bg-accent-gold text-bg-page px-2 py-0.5 text-[8px] font-semibold disabled:opacity-70"
        >
          {event.is_saved ? 'Saved ✓' : 'Save'}
        </button>
      </span>
      {saveError && <span className="text-[8px] text-red-500">{saveError}</span>}
    </span>
  )
}
