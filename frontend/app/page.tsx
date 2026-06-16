'use client'
import { useState } from 'react'
import useSWR from 'swr'
import { getDigest } from '@/lib/api'
import DigestSection from '@/components/DigestSection'
import FeedFilters from '@/components/FeedFilters'
import type { FeedFilterState } from '@/components/FeedFilters'
import FeedSection from '@/components/FeedSection'
import { useAppShell } from '@/components/AppShell'

const DEFAULT_FILTERS: FeedFilterState = {
  category: null, datePreset: 'any', isFree: false, q: '',
}

export default function DashboardPage() {
  const [filters, setFilters] = useState<FeedFilterState>(DEFAULT_FILTERS)
  const {
    openOverlay, handleFeedback, handleSave, isOptimisticallySaved, optimisticSentimentFor,
  } = useAppShell()

  // Prefetched here so digest cards can pass justification when opened.
  const { data: digest } = useSWR('/digest', getDigest)

  function handleDigestClick(eventId: string) {
    const justification = digest?.picks.find((p) => p.event.id === eventId)?.justification ?? null
    openOverlay(eventId, justification)
  }

  return (
    <>
      <DigestSection
        onCardClick={handleDigestClick}
        onFeedback={handleFeedback}
        onSave={handleSave}
        isOptimisticallySaved={isOptimisticallySaved}
        optimisticSentimentFor={optimisticSentimentFor}
      />
      <FeedFilters filters={filters} onChange={setFilters} />
      <FeedSection
        filters={filters}
        onCardClick={openOverlay}
        onFeedback={handleFeedback}
        onSave={handleSave}
        isOptimisticallySaved={isOptimisticallySaved}
        optimisticSentimentFor={optimisticSentimentFor}
      />
    </>
  )
}
