'use client'
import { useEffect, useRef, useState } from 'react'
import useSWRInfinite from 'swr/infinite'
import { getEvents } from '@/lib/api'
import type { EventsFeedResponse, Sentiment } from '@/lib/types'
import type { FeedFilterState } from './FeedFilters'
import EventCard from './EventCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  filters: FeedFilterState
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  onSave: (id: string, save: boolean) => void
  isOptimisticallySaved?: (id: string) => boolean | undefined
  optimisticSentimentFor?: (id: string) => Sentiment | null | undefined
}

function filtersToQuery(filters: FeedFilterState) {
  const q: Record<string, string> = {}
  if (filters.category) q.category = filters.category
  if (filters.isFree) q.is_free = 'true'
  if (filters.q)      q.q = filters.q
  if (filters.datePreset === 'today') {
    q.date_from = new Date().toISOString().slice(0, 10)
    q.date_to   = new Date().toISOString().slice(0, 10)
  } else if (filters.datePreset === 'this-week') {
    const now  = new Date()
    const end  = new Date(now); end.setDate(now.getDate() + 7)
    q.date_from = now.toISOString().slice(0, 10)
    q.date_to   = end.toISOString().slice(0, 10)
  } else if (filters.datePreset === 'this-weekend') {
    const now = new Date()
    const day = now.getDay()
    const sat = new Date(now); sat.setDate(now.getDate() + ((6 - day + 7) % 7))
    const sun = new Date(sat); sun.setDate(sat.getDate() + 1)
    q.date_from = sat.toISOString().slice(0, 10)
    q.date_to   = sun.toISOString().slice(0, 10)
  }
  return q
}

export default function FeedSection({
  filters, onCardClick, onFeedback, onSave, isOptimisticallySaved, optimisticSentimentFor,
}: Props) {
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [debouncedFilters, setDebouncedFilters] = useState(filters)

  useEffect(() => {
    const id = setTimeout(() => setDebouncedFilters(filters), 300)
    return () => clearTimeout(id)
  }, [filters])

  const getKey = (pageIndex: number, prev: EventsFeedResponse | null) => {
    if (prev && prev.events.length < prev.page_size) return null
    return ['/events', debouncedFilters, pageIndex + 1]
  }

  const { data, isLoading, isValidating, size, setSize } = useSWRInfinite(
    getKey,
    ([, f, page]) => getEvents({ ...filtersToQuery(f as FeedFilterState), page: page as number, page_size: 20 }),
    { revalidateFirstPage: false }
  )

  const events = data?.flatMap((p) => p.events) ?? []
  const isEmpty = !isLoading && !isValidating && events.length === 0
  const isLoadingMore = isValidating && size > (data?.length ?? 0)
  const hasError = !isLoading && data === undefined && !isValidating

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting && !isValidating) setSize((s) => s + 1) },
      { threshold: 0 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [isValidating, setSize])

  return (
    <div className="flex-1 overflow-y-auto px-5 py-3 bg-bg-page flex flex-col gap-2">
      <p className="text-[10px] uppercase tracking-widest text-accent-gold mb-1">Upcoming Events</p>

      {isLoading && Array.from({ length: 5 }).map((_, i) => (
        <SkeletonCard key={i} variant="feed" />
      ))}

      {hasError && (
        <p className="text-[11px] text-red-600 italic">
          Could not load events.{' '}
          <button onClick={() => setSize(1)} className="text-accent-gold underline">Retry</button>
        </p>
      )}

      {isEmpty && (
        <p className="text-[11px] text-text-muted italic">
          No events match your filters.
        </p>
      )}

      {events.map((evt) => (
        <EventCard
          key={evt.id}
          variant="feed"
          data={evt}
          onCardClick={onCardClick}
          onFeedback={onFeedback}
          onSave={onSave}
          forceSaved={isOptimisticallySaved?.(evt.id)}
          forceSentiment={optimisticSentimentFor?.(evt.id)}
        />
      ))}

      {isLoadingMore && <p className="text-[10px] italic text-text-muted text-center py-1">Loading more…</p>}

      <div ref={sentinelRef} className="h-1" />
    </div>
  )
}
