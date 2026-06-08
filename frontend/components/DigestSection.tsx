'use client'
import useSWR from 'swr'
import { getDigest, refreshDigest as refreshDigestApi } from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import EventCard from './EventCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

export default function DigestSection({ onCardClick, onFeedback, onSave }: Props) {
  const { data, isLoading, error, mutate } = useSWR('/digest', getDigest)

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

        {error && (
          <p className="text-[10px] text-red-600 italic py-2">
            Could not load picks.{' '}
            <button onClick={() => mutate()} className="text-accent-gold underline">Retry</button>
          </p>
        )}

        {!isLoading && !error && data?.picks.length === 0 && (
          <p className="text-[10px] text-text-muted italic py-2">
            No picks yet — check back after events are loaded.{' '}
            <button onClick={handleRefresh} className="text-accent-gold underline">Refresh now</button>
          </p>
        )}

        {data?.picks.map((pick) => (
          <EventCard
            key={pick.event.id}
            variant="digest"
            data={pick}
            onCardClick={onCardClick}
            onFeedback={onFeedback}
            onSave={onSave}
          />
        ))}
      </div>
    </div>
  )
}
