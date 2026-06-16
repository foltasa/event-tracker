'use client'
import useSWR from 'swr'
import { getDigest, getEvents, refreshDigest as refreshDigestApi } from '@/lib/api'
import type { DigestPick, Sentiment } from '@/lib/types'
import EventCard from './EventCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
  isOptimisticallySaved?: (id: string) => boolean
}

export default function DigestSection({ onCardClick, onFeedback, onSave, isOptimisticallySaved }: Props) {
  const { data, isLoading, error, mutate } = useSWR('/digest', getDigest)

  // Fallback: when the recommender fails, show the next 3 upcoming events so
  // the panel never collapses to a bare error message.
  const today = new Date().toISOString().slice(0, 10)
  const { data: fallback } = useSWR(
    error ? ['/events', 'digest-fallback', today] : null,
    () => getEvents({ page: 1, page_size: 3, date_from: today }),
  )
  const fallbackPicks: DigestPick[] = (fallback?.events ?? []).map((e) => ({
    event: e,
    justification: '',
  }))

  async function handleRefresh() {
    const fresh = await refreshDigestApi()
    mutate(fresh, false)
  }

  return (
    <div className="flex-shrink-0 border-b-2 border-border bg-bg-page">
      <div className="flex items-baseline justify-between px-5 pt-4 pb-2">
        <div className="flex items-baseline gap-2">
          <span className="font-serif font-bold text-sm text-text-primary">Today's Picks</span>
          {data && (
            <span className="text-[10px] italic text-text-muted">
              {data.picks.length} picks · generated {new Date(data.generated_at).toLocaleTimeString('en-DE', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          {error && fallbackPicks.length > 0 && (
            <span className="text-[10px] italic text-text-muted">
              showing upcoming events while picks are unavailable
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="text-[10px] text-accent-gold border border-border rounded px-2 py-0.5 hover:bg-accent-gold-light"
        >
          ↻ Refresh
        </button>
      </div>

      <div className="flex gap-2.5 overflow-x-auto px-5 pb-4">
        {isLoading && Array.from({ length: 3 }).map((_, i) => (
          <SkeletonCard key={i} variant="digest" />
        ))}

        {!isLoading && !error && data?.picks.length === 0 && (
          <p className="text-[10px] text-text-muted italic py-2">
            No picks yet — check back after events are loaded.{' '}
            <button onClick={handleRefresh} className="text-accent-gold underline">Refresh now</button>
          </p>
        )}

        {!error && data?.picks.map((pick) => (
          <EventCard
            key={pick.event.id}
            variant="digest"
            data={pick}
            onCardClick={onCardClick}
            onFeedback={onFeedback}
            onSave={onSave}
            forceSaved={isOptimisticallySaved?.(pick.event.id)}
          />
        ))}

        {error && fallbackPicks.map((pick) => (
          <EventCard
            key={pick.event.id}
            variant="digest"
            data={pick}
            onCardClick={onCardClick}
            onFeedback={onFeedback}
            onSave={onSave}
            forceSaved={isOptimisticallySaved?.(pick.event.id)}
          />
        ))}

        {error && fallbackPicks.length === 0 && (
          <p className="text-[10px] text-text-muted italic py-2">
            Picks unavailable right now.
          </p>
        )}
      </div>
    </div>
  )
}
