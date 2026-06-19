'use client'
import { Fragment, useRef, useEffect, useState } from 'react'
import { useChat } from '@/hooks/useChat'
import type { Sentiment } from '@/lib/types'
import { parseMessageContent } from '@/lib/parseMessageContent'
import EventChip from '@/components/EventChip'

interface Props {
  sessionId: string
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  onSave: (id: string, save: boolean) => void
}

export default function ChatPanel({ sessionId, onCardClick, onFeedback, onSave }: Props) {
  const { messages, isStreaming, currentTool, error, sendMessage, clearSession } = useChat(sessionId)
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

  async function handleDelete() {
    if (!window.confirm('Delete the entire chat history?')) return
    await clearSession()
  }

  const lastIdx = messages.length - 1

  return (
    <div className="flex flex-col w-[280px] flex-shrink-0 bg-bg-chat border-l border-border">
      {/* Header */}
      <div className="px-3.5 py-2.5 border-b border-border bg-accent-gold-light flex-shrink-0">
        <p className="font-serif font-bold text-xs text-text-primary">Chat Assistant</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-2.5 flex flex-col gap-2">
        {messages.map((msg, i) => {
          const showIndicator =
            isStreaming &&
            i === lastIdx &&
            msg.role === 'assistant' &&
            (currentTool !== null || msg.content === '')
          const indicatorText = currentTool ? `${currentTool} running…` : 'thinking…'
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="self-end max-w-[88%] rounded-lg rounded-br-sm bg-bg-surface px-2.5 py-1.5 text-[10px] italic text-text-primary">
                {msg.content}
              </div>
            )
          }
          return (
            <Fragment key={msg.id}>
              {showIndicator && (
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                  <span className="text-[9px] italic text-accent-gold">{indicatorText}</span>
                </div>
              )}
              <div className="self-start max-w-[92%] rounded-lg rounded-bl-sm border border-border bg-white px-2.5 py-1.5 text-[10px] text-text-primary">
                <p className="leading-relaxed whitespace-pre-wrap">
                  {parseMessageContent(msg.content).map((seg, si) =>
                    seg.type === 'event'
                      ? <EventChip key={`${msg.id}-ev-${si}`} eventId={seg.id} />
                      : <span key={`${msg.id}-tx-${si}`}>{seg.value}</span>
                  )}
                </p>
                {msg.isStreaming && msg.content !== '' && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
              </div>
            </Fragment>
          )
        })}
        {error && <p className="text-[9px] text-red-500 italic">{error}</p>}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-1.5 px-3 py-2 border-t border-border">
        <input
          value={input}
          disabled={isStreaming}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask anything about events…"
          className="flex-1 text-[10px] border border-border rounded px-2 py-1.5 bg-white disabled:bg-bg-surface"
        />
        <button
          aria-label="send"
          disabled={isStreaming}
          onClick={handleSubmit}
          className="bg-accent-gold text-bg-page rounded px-2.5 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          ↑
        </button>
        <button
          aria-label="Delete chat"
          onClick={handleDelete}
          className="bg-red-600 text-white rounded px-2.5 py-1.5 text-xs font-semibold hover:bg-red-700"
        >
          🗑
        </button>
      </div>
    </div>
  )
}
