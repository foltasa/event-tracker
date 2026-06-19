'use client'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import useSWR, { useSWRConfig } from 'swr'
import { ChatProvider } from '@/lib/ChatContext'
import {
  deleteFeedback,
  getEventDetail,
  postFeedback,
  removeFromCalendar,
  saveToCalendar,
} from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import TopNav from '@/components/TopNav'
import ChatPanel from '@/components/ChatPanel'
import EventDetailOverlay from '@/components/EventDetailOverlay'

interface AppShellCtxValue {
  openOverlay: (eventId: string, justification?: string | null) => void
  handleSave: (eventId: string, shouldBeSaved: boolean) => Promise<void>
  handleFeedback: (eventId: string, sentiment: Sentiment | null) => Promise<void>
  // Returns the optimistic override if present, otherwise undefined (caller
  // should fall back to the cached `is_saved` field).
  isOptimisticallySaved: (eventId: string) => boolean | undefined
  optimisticSentimentFor: (eventId: string) => Sentiment | null | undefined
}

const AppShellCtx = createContext<AppShellCtxValue | null>(null)

export function useAppShell(): AppShellCtxValue {
  const ctx = useContext(AppShellCtx)
  if (!ctx) throw new Error('useAppShell must be used within AppShell')
  return ctx
}

function EventDetailOverlayLoader({
  eventId, justification, onClose, onSave, onFeedback,
}: {
  eventId: string
  justification: string | null
  onClose: () => void
  onSave: (id: string, save: boolean) => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
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

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const active: 'dashboard' | 'calendar' =
    pathname?.startsWith('/calendar') ? 'calendar' : 'dashboard'
  const dateLabel = new Date().toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })

  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const [activeJustification, setActiveJustification] = useState<string | null>(null)
  // Two override maps so we can express "optimistically saved" *and*
  // "optimistically unsaved" / "optimistically cleared". Presence in the map
  // means "override the server-truth"; absence means "trust the cache".
  const [optSaved, setOptSaved] = useState<Map<string, boolean>>(new Map())
  const [optSentiment, setOptSentiment] = useState<Map<string, Sentiment | null>>(new Map())
  const { mutate } = useSWRConfig()

  const openOverlay = useCallback((eventId: string, justification: string | null = null) => {
    setActiveEventId(eventId)
    setActiveJustification(justification)
  }, [])

  const closeOverlay = useCallback(() => {
    setActiveEventId(null)
    setActiveJustification(null)
  }, [])

  const fanOutEventCaches = useCallback((eventId: string) => {
    mutate(`/events/${eventId}`)
    mutate('/digest')
    mutate('/calendar')
    mutate((key) => Array.isArray(key) && key[0] === '/events')
    mutate((key) => Array.isArray(key) && key[0] === '/appointments')
  }, [mutate])

  const handleFeedback = useCallback(async (eventId: string, sentiment: Sentiment | null) => {
    setOptSentiment((m) => new Map(m).set(eventId, sentiment))
    try {
      if (sentiment === null) await deleteFeedback(eventId)
      else                    await postFeedback({ event_id: eventId, sentiment, comment: null })
      fanOutEventCaches(eventId)
    } catch {
      setOptSentiment((m) => { const n = new Map(m); n.delete(eventId); return n })
    }
  }, [fanOutEventCaches])

  const handleSave = useCallback(async (eventId: string, shouldBeSaved: boolean) => {
    setOptSaved((m) => new Map(m).set(eventId, shouldBeSaved))
    try {
      if (shouldBeSaved) await saveToCalendar(eventId)
      else                await removeFromCalendar(eventId)
      fanOutEventCaches(eventId)
    } catch {
      setOptSaved((m) => { const n = new Map(m); n.delete(eventId); return n })
    }
  }, [fanOutEventCaches])

  const isOptimisticallySaved = useCallback(
    (eventId: string) => optSaved.get(eventId),
    [optSaved],
  )

  const optimisticSentimentFor = useCallback(
    (eventId: string) => (optSentiment.has(eventId) ? optSentiment.get(eventId) : undefined),
    [optSentiment],
  )

  return (
    <AppShellCtx.Provider
      value={{ openOverlay, handleSave, handleFeedback, isOptimisticallySaved, optimisticSentimentFor }}
    >
      <div className="flex flex-col h-screen overflow-hidden bg-bg-page">
        <TopNav active={active} date={`Hamburg · ${dateLabel}`} />
        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 flex flex-col overflow-hidden">
            {children}
          </div>
          <ChatPanel
            sessionId="dashboard"
            model="gpt-4o-mini"
            dailyCost={0}
            onCardClick={openOverlay}
            onFeedback={handleFeedback}
            onSave={handleSave}
          />
        </div>
      </div>
      {activeEventId && (
        <EventDetailOverlayLoader
          eventId={activeEventId}
          justification={activeJustification}
          onClose={closeOverlay}
          onSave={handleSave}
          onFeedback={handleFeedback}
        />
      )}
    </AppShellCtx.Provider>
  )
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <ChatProvider>
      <Shell>{children}</Shell>
    </ChatProvider>
  )
}
