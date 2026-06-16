'use client'
import { useState, useCallback } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { postFeedback, saveToCalendar, getDigest, getEventDetail } from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import TopNav from '@/components/TopNav'
import DigestSection from '@/components/DigestSection'
import FeedFilters from '@/components/FeedFilters'
import type { FeedFilterState } from '@/components/FeedFilters'
import FeedSection from '@/components/FeedSection'
import ChatPanel from '@/components/ChatPanel'
import EventDetailOverlay from '@/components/EventDetailOverlay'

const DEFAULT_FILTERS: FeedFilterState = {
  category: null, datePreset: 'any', isFree: false, q: '',
}

export default function DashboardPage() {
  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS)
  const { mutate } = useSWRConfig()

  const { data: digest } = useSWR('/digest', getDigest)

  const handleFeedback = useCallback(async (eventId: string, sentiment: Sentiment) => {
    await postFeedback({ event_id: eventId, sentiment, comment: null })
  }, [])

  const handleSave = useCallback(async (eventId: string) => {
    await saveToCalendar(eventId)
    mutate(`/events/${eventId}`)
  }, [mutate])

  const handleCardClick = useCallback((eventId: string) => {
    setActiveEventId(eventId)
  }, [])

  const today = new Date().toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })
  const model = 'gpt-4o-mini'
  const activeJustification = digest?.picks.find((p) => p.event.id === activeEventId)?.justification ?? null

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg-page">
      <TopNav active="dashboard" date={`Hamburg · ${today}`} />

      <div className="flex flex-1 overflow-hidden">
        {/* Left column */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <DigestSection
            onCardClick={handleCardClick}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
          <FeedFilters filters={filters} onChange={setFilters} />
          <FeedSection
            filters={filters}
            onCardClick={handleCardClick}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
        </div>

        {/* Chat panel */}
        <ChatPanel
          sessionId="dashboard"
          model={model}
          dailyCost={0}
          onCardClick={handleCardClick}
          onFeedback={handleFeedback}
          onSave={handleSave}
        />
      </div>

      {/* Event detail overlay */}
      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          justification={activeJustification}
          onClose={() => setActiveEventId(null)}
          onFeedback={handleFeedback}
          onSave={handleSave}
        />
      )}
    </div>
  )
}

function EventDetailOverlayLoader({
  eventId, justification, onClose, onFeedback, onSave,
}: {
  eventId: string
  justification: string | null
  onClose: () => void
  onFeedback: (id: string, s: Sentiment) => void
  onSave: (id: string) => void
}) {
  const { data: event } = useSWR(`/events/${eventId}`, () => getEventDetail(eventId))

  if (!event) return null

  return (
    <EventDetailOverlay
      event={event}
      justification={justification}
      onClose={onClose}
      onFeedback={onFeedback}
      onSave={onSave}
    />
  )
}
