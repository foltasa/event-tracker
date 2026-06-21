'use client'
import useSWR, { useSWRConfig } from 'swr'
import { useState, type KeyboardEvent, type MouseEvent } from 'react'
import { getEventDetail, removeFromCalendar, saveToCalendar, slotInRecommendation } from '@/lib/api'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit',
  })
}

interface Props {
  eventId: string
  onCardClick?: (id: string) => void
}

export default function EventChip({ eventId, onCardClick }: Props) {
  const { data: event, error, mutate } = useSWR(
    `/events/${eventId}`,
    () => getEventDetail(eventId),
  )
  const { mutate: globalMutate } = useSWRConfig()
  const [saveError, setSaveError] = useState<string | null>(null)

  if (error) return <span className="text-[10px] text-text-muted">[event not found]</span>
  if (!event) {
    return (
      <span
        data-testid="chip-skeleton"
        className="block h-10 w-full rounded bg-bg-surface animate-pulse my-1"
      />
    )
  }

  async function handleToggle(e: MouseEvent) {
    e.stopPropagation()
    if (!event) return
    const prev = event
    const kind = event.calendar_kind
    setSaveError(null)
    const action: 'save' | 'slot-in' | 'remove' =
      kind === 'saved' ? 'remove' : kind === 'recommendation' ? 'slot-in' : 'save'
    const optimistic =
      action === 'remove'
        ? { ...event, is_saved: false, calendar_kind: null }
        : { ...event, is_saved: true, calendar_kind: 'saved' as const }
    mutate(optimistic, false)
    try {
      if (action === 'save')         await saveToCalendar(eventId)
      else if (action === 'slot-in') await slotInRecommendation(eventId)
      else                            await removeFromCalendar(eventId)
      mutate()
      globalMutate('/calendar')
      globalMutate('/digest')
      globalMutate((key) => Array.isArray(key) && key[0] === '/events')
      globalMutate((key) => Array.isArray(key) && key[0] === '/appointments')
    } catch {
      mutate(prev, false)
      setSaveError(action === 'remove' ? 'Failed to remove — try again' : 'Failed to save — try again')
    }
  }

  function handleOpen() {
    onCardClick?.(eventId)
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (!onCardClick) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleOpen()
    }
  }

  const interactive = Boolean(onCardClick)

  return (
    <span
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? handleOpen : undefined}
      onKeyDown={interactive ? handleKeyDown : undefined}
      className={`block w-full max-w-full bg-accent-gold-light border border-accent-gold/30 rounded px-2 py-1 my-1 text-[10px] text-text-primary box-border ${
        interactive ? 'cursor-pointer hover:border-accent-gold/60' : ''
      }`}
    >
      <span className="flex items-center gap-1.5 min-w-0">
        <span className="uppercase tracking-wider font-semibold text-accent-gold flex-shrink-0">{event.category}</span>
        <span className="font-semibold truncate min-w-0 flex-1">{event.title}</span>
        <button
          onClick={handleToggle}
          className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold ${
            event.calendar_kind === 'saved'
              ? 'bg-accent-gold-light text-accent-gold border border-accent-gold/40'
              : 'bg-accent-gold text-bg-page'
          }`}
        >
          {event.calendar_kind === 'saved' ? 'Slot Out' : 'Slot in'}
        </button>
      </span>
      <span className="block text-text-muted truncate mt-0.5">
        {formatDate(event.start_datetime)}{event.venue_name ? ` · ${event.venue_name}` : ''}
      </span>
      {saveError && <span className="block text-[9px] text-red-500 mt-0.5">{saveError}</span>}
    </span>
  )
}
