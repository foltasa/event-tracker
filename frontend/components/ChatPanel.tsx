'use client'
import { useRef, useEffect, useState } from 'react'
import { useChat } from '@/hooks/useChat'
import type { Sentiment } from '@/lib/types'

interface Props {
  sessionId: string
  model: string
  dailyCost: number
  onCardClick: (id: string) => void
  onFeedback: (id: string, sentiment: Sentiment) => void
  onSave: (id: string) => void
}

export default function ChatPanel({ sessionId, model, dailyCost, onCardClick, onFeedback, onSave }: Props) {
  const { messages, isStreaming, error, sendMessage } = useChat(sessionId)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleSubmit() {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    sendMessage(text)
  }

  return (
    <div className="flex flex-col w-[280px] flex-shrink-0 bg-bg-chat border-l border-border">
      {/* Header */}
      <div className="px-3.5 py-2.5 border-b border-border bg-accent-gold-light flex-shrink-0">
        <p className="font-serif font-bold text-xs text-text-primary">Chat Assistant</p>
        <p className="text-[9px] text-accent-gold mt-0.5">{model} · ${dailyCost.toFixed(4)} today</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-2.5 flex flex-col gap-2">
        {messages.map((msg) => {
          if (msg.role === 'tool') {
            return (
              <div key={msg.id} className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                <span className="text-[9px] italic text-accent-gold">{msg.toolName} running…</span>
              </div>
            )
          }
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="self-end max-w-[88%] rounded-lg rounded-br-sm bg-bg-surface px-2.5 py-1.5 text-[10px] italic text-text-primary">
                {msg.content}
              </div>
            )
          }
          return (
            <div key={msg.id} className="self-start max-w-[92%] rounded-lg rounded-bl-sm border border-border bg-white px-2.5 py-1.5 text-[10px] text-text-primary">
              <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              {msg.isStreaming && <span className="inline-block w-1 h-3 bg-text-muted animate-pulse ml-0.5" />}
              {msg.tokenUsage && (
                <p className="text-[8px] text-text-muted mt-1 text-right">
                  {msg.tokenUsage.input_tokens} in · {msg.tokenUsage.output_tokens} out · ${msg.tokenUsage.estimated_cost_usd.toFixed(4)}
                </p>
              )}
            </div>
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
      </div>
    </div>
  )
}
