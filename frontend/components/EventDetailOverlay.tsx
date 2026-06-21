'use client'
import { Fragment, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useChat } from '@/hooks/useChat'
import type { EventWithContext, Sentiment } from '@/lib/types'
import { parseMessageContent } from '@/lib/parseMessageContent'
import EventChip from '@/components/EventChip'
import { useAppShell } from '@/components/AppShell'

interface Props {
  event: EventWithContext
  justification: string | null
  onClose: () => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  onSave: (id: string, save: boolean) => void
  onSlotIn: (id: string) => void
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
  })
}

function formatPrice(min: number | null, max: number | null, isFree: boolean) {
  if (isFree) return 'Free'
  if (min == null) return 'Price unknown'
  if (max != null && max !== min) return `€${min} – €${max}`
  return `€${min}`
}

function EventChat({ eventId, onCardClick }: { eventId: string; onCardClick: (id: string) => void }) {
  const { messages, isStreaming, currentTool, error, sendMessage } = useChat(`event_${eventId}`)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentTool])

  function handleSubmit() {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    sendMessage(text)
  }

  const lastIdx = messages.length - 1

  return (
    <>
      <div className="flex flex-col gap-2 px-4 py-3">
        {messages.map((msg, i) => {
          const showIndicator =
            isStreaming &&
            i === lastIdx &&
            msg.role === 'assistant' &&
            (currentTool !== null || msg.content === '')
          const indicatorText = currentTool ? `${currentTool} running…` : 'thinking…'
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="self-end max-w-[85%] rounded-lg rounded-br-sm bg-bg-surface px-3 py-1.5 text-[11px] italic text-text-primary">
                {msg.content}
              </div>
            )
          }
          return (
            <Fragment key={msg.id}>
              {showIndicator && (
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                  <span className="text-[10px] italic text-accent-gold">{indicatorText}</span>
                </div>
              )}
              <div className="self-start max-w-[90%] min-w-0 rounded-lg rounded-bl-sm border border-border bg-white px-3 py-1.5 text-[11px] text-text-primary leading-relaxed">
                {parseMessageContent(msg.content).map((seg, si) =>
                  seg.type === 'event'
                    ? <EventChip key={`${msg.id}-ev-${si}`} eventId={seg.id} onCardClick={onCardClick} />
                    : <span key={`${msg.id}-tx-${si}`}>{seg.value}</span>
                )}
                {msg.isStreaming && msg.content !== '' && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
              </div>
            </Fragment>
          )
        })}
        {error && <p className="text-[10px] text-red-500 italic">{error}</p>}
        <div ref={bottomRef} />
      </div>

      <div className="sticky bottom-0 flex gap-2 px-4 py-2.5 border-t border-border bg-bg-chat">
        <input
          value={input}
          disabled={isStreaming}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask about this event, or leave a note for the agent…"
          className="flex-1 text-[11px] border border-border rounded px-2.5 py-1.5 bg-white disabled:bg-bg-surface"
        />
        <button
          disabled={isStreaming}
          onClick={handleSubmit}
          className="bg-accent-gold text-bg-page rounded px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          ↑
        </button>
      </div>
      <p className="text-[9px] text-text-muted text-right px-4 pb-2 bg-bg-chat">
        Messages left here inform your taste profile
      </p>
    </>
  )
}

function OverlayContent({ event, justification, onClose, onFeedback, onSave, onSlotIn }: Props) {
  const { isOptimisticallySaved, optimisticSentimentFor, optimisticCalendarKindFor, openOverlay } = useAppShell()
  const optSent = optimisticSentimentFor(event.id)
  const sentiment: Sentiment | null = optSent !== undefined ? optSent : (event.user_sentiment ?? null)
  const optSaved = isOptimisticallySaved(event.id)
  const isSaved = optSaved !== undefined ? optSaved : event.is_saved
  const optKind = optimisticCalendarKindFor(event.id)
  const calendarKind: 'saved' | 'recommendation' | null =
    optKind !== undefined ? optKind : (event.calendar_kind ?? (isSaved ? 'saved' : null))

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      data-testid="overlay-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-text-primary/55 px-4"
      onClick={onClose}
    >
      <div
        className="relative bg-bg-page rounded-xl w-full max-w-lg max-h-[88vh] flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Hero */}
        <div
          className="relative h-36 flex-shrink-0 flex flex-col justify-between p-3"
          style={event.image_url
            ? { backgroundImage: `url(${event.image_url})`, backgroundSize: 'cover', backgroundPosition: 'center' }
            : { background: 'linear-gradient(160deg, #c4a882, #8a6040)' }
          }
        >
          <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/60" />
          <div className="relative z-10 flex justify-between">
            <div className="flex gap-2">
              <span className="rounded px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold bg-accent-gold text-bg-page">
                {event.category}
              </span>
              <a
                href={event.source_url}
                target="_blank"
                rel="noreferrer"
                className="rounded px-2 py-0.5 text-[10px] bg-black/30 text-white hover:bg-black/50"
                onClick={(e) => e.stopPropagation()}
              >
                {event.source} ↗
              </a>
            </div>
            <button
              aria-label="Close overlay"
              onClick={onClose}
              className="w-6 h-6 rounded-full bg-black/30 text-white flex items-center justify-center hover:bg-black/50 text-xs"
            >
              ✕
            </button>
          </div>
          <div className="relative z-10">
            <h2 className="font-serif font-bold text-lg text-white leading-tight">{event.title}</h2>
            <p className="text-[12px] text-white/80 mt-1">{formatDate(event.start_datetime)}</p>
          </div>
        </div>

        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 border-b border-border bg-white flex-shrink-0">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-accent-gold">Venue</p>
            <p className="text-[12px] font-semibold text-text-primary">{event.venue_name ?? 'TBC'}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-accent-gold">Price</p>
            <p className="text-[12px] font-semibold text-text-primary">{formatPrice(event.price_min, event.price_max, event.is_free)}</p>
          </div>
          {event.tags.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {event.tags.map((tag) => (
                <span key={tag} className="rounded bg-accent-gold-light text-accent-gold text-[10px] px-1.5 py-0.5">{tag}</span>
              ))}
            </div>
          )}
          <div className="ml-auto flex gap-1.5 items-center">
            <button
              aria-label="Like"
              onClick={() => onFeedback(event.id, sentiment === 'like' ? null : 'like')}
              className={`rounded border px-2 py-1 text-xs ${sentiment === 'like' ? 'bg-accent-gold border-accent-gold text-bg-page' : 'bg-white border-border'}`}
            >
              👍
            </button>
            <button
              aria-label="Dislike"
              onClick={() => onFeedback(event.id, sentiment === 'dislike' ? null : 'dislike')}
              className={`rounded border px-2 py-1 text-xs ${sentiment === 'dislike' ? 'bg-text-secondary border-text-secondary text-bg-page' : 'bg-white border-border'}`}
            >
              👎
            </button>
            {calendarKind === 'recommendation' ? (
              <>
                <button
                  onClick={() => onSlotIn(event.id)}
                  className="rounded text-[11px] font-semibold px-3 py-1 bg-accent-gold text-bg-page"
                >
                  Slot in
                </button>
                <button
                  onClick={() => onSave(event.id, false)}
                  className="rounded text-[11px] font-semibold px-3 py-1 border border-accent-gold text-accent-gold bg-transparent"
                >
                  Slot out
                </button>
              </>
            ) : (
              <button
                onClick={() => onSave(event.id, calendarKind !== 'saved')}
                className={`rounded text-[11px] font-semibold px-3 py-1 ${
                  calendarKind === 'saved'
                    ? 'bg-accent-gold-light text-accent-gold'
                    : 'bg-accent-gold text-bg-page'
                }`}
              >
                {calendarKind === 'saved' ? 'Slot Out' : 'Slot in'}
              </button>
            )}
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {/* Description */}
          <div className="px-4 pt-4 pb-2 bg-bg-page">
            <p className="text-[10px] uppercase tracking-widest text-accent-gold mb-2">About this event</p>
            <p className="font-serif text-xs text-text-primary leading-7">
              {event.summary ?? 'No description available.'}
            </p>
          </div>

          {/* AI justification */}
          {justification && (
            <div className="mx-4 my-3 border-l-2 border-accent-gold rounded-r-lg bg-accent-gold-light px-3 py-2 text-[12px] italic text-text-primary leading-relaxed">
              ✦ "{justification}"
            </div>
          )}

          {/* Per-event chat */}
          <div className="border-t-2 border-border mt-1 bg-bg-chat">
            <div className="px-4 pt-3 pb-1">
              <p className="text-[10px] uppercase tracking-widest text-accent-gold">Chat about this event</p>
              <p className="text-[10px] text-text-muted mt-0.5">Ask questions or leave a note for the agent</p>
            </div>
            <EventChat eventId={event.id} onCardClick={openOverlay} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function EventDetailOverlay(props: Props) {
  if (typeof document === 'undefined') return null
  return createPortal(<OverlayContent {...props} />, document.body)
}
