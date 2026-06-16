'use client'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import useSWR, { useSWRConfig } from 'swr'
import { ChatProvider } from '@/lib/ChatContext'
import { getEventDetail, postFeedback, saveToCalendar } from '@/lib/api'
import type { Sentiment } from '@/lib/types'
import TopNav from '@/components/TopNav'
import ChatPanel from '@/components/ChatPanel'
import EventDetailOverlay from '@/components/EventDetailOverlay'

interface OverlayCtxValue {
  openOverlay: (eventId: string, justification?: string | null) => void
  handleSave: (eventId: string) => Promise<void>
  handleFeedback: (eventId: string, sentiment: Sentiment) => Promise<void>
  isOptimisticallySaved: (eventId: string) => boolean
}

const OverlayCtx = createContext<OverlayCtxValue | null>(null)

export function useAppShell(): OverlayCtxValue {
  const ctx = useContext(OverlayCtx)
  if (!ctx) throw new Error('useAppShell must be used within AppShell')
  return ctx
}

function EventDetailOverlayLoader({
  eventId, justification, onClose, onSave, onFeedback,
}: {
  eventId: string
  justification: string | null
  onClose: () => void
  onSave: (id: string) => void
  onFeedback: (id: string, s: Sentiment) => void
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
  const active: 'dashboard' | 'calendar' | 'settings' =
    pathname?.startsWith('/calendar') ? 'calendar'
    : pathname?.startsWith('/settings') ? 'settings'
    : 'dashboard'
  const dateLabel = new Date().toLocaleDateString('en-DE', { month: 'long', day: 'numeric' })

  const [activeEventId, setActiveEventId] = useState<string | null>(null)
  const [activeJustification, setActiveJustification] = useState<string | null>(null)
  const [optimisticSaved, setOptimisticSaved] = useState<Set<string>>(new Set())
  const { mutate } = useSWRConfig()

  const openOverlay = useCallback((eventId: string, justification: string | null = null) => {
    setActiveEventId(eventId)
    setActiveJustification(justification)
  }, [])

  const closeOverlay = useCallback(() => {
    setActiveEventId(null)
    setActiveJustification(null)
  }, [])

  const handleFeedback = useCallback(async (eventId: string, sentiment: Sentiment) => {
    await postFeedback({ event_id: eventId, sentiment, comment: null })
    mutate(`/events/${eventId}`)
  }, [mutate])

  const handleSave = useCallback(async (eventId: string) => {
    setOptimisticSaved((s) => {
      const next = new Set(s)
      next.add(eventId)
      return next
    })
    try {
      await saveToCalendar(eventId)
      mutate(`/events/${eventId}`)
      mutate('/digest')
      mutate('/calendar')
      mutate((key) => Array.isArray(key) && key[0] === '/events')
    } catch {
      setOptimisticSaved((s) => {
        const next = new Set(s)
        next.delete(eventId)
        return next
      })
    }
  }, [mutate])

  const isOptimisticallySaved = useCallback(
    (eventId: string) => optimisticSaved.has(eventId),
    [optimisticSaved],
  )

  return (
    <OverlayCtx.Provider value={{ openOverlay, handleSave, handleFeedback, isOptimisticallySaved }}>
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
    </OverlayCtx.Provider>
  )
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <ChatProvider>
      <Shell>{children}</Shell>
    </ChatProvider>
  )
}
