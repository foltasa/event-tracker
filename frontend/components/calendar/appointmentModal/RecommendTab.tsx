'use client'
import { useState } from 'react'
import { recommendAppointment } from '@/lib/api'

interface Initial {
  day: string
  start_at?: string | null
  end_at?: string | null
}

interface Bubble { role: 'user' | 'assistant'; content: string; id: string }

export default function RecommendTab({ initial }: { initial: Initial }) {
  const [input, setInput] = useState('')
  const [focused, setFocused] = useState(false)
  const [messages, setMessages] = useState<Bubble[]>([])
  const [busy, setBusy] = useState(false)

  const showPlaceholder = input.length === 0 && !focused && messages.length === 0

  async function handleSubmit() {
    const text = input.trim()
    if (!text || busy) return
    setBusy(true)
    setInput('')
    const userBubble: Bubble = { id: `u-${Date.now()}`, role: 'user', content: text }
    setMessages((m) => [...m, userBubble])
    try {
      const out = await recommendAppointment({
        day: initial.day,
        start_at: initial.start_at ?? null,
        end_at: initial.end_at ?? null,
        message: text,
      })
      setMessages((m) => [...m, { id: `a-${Date.now()}`, role: 'assistant', content: out.message }])
    } catch {
      setMessages((m) => [...m, {
        id: `a-${Date.now()}`, role: 'assistant', content: "Couldn't reach assistant",
      }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col p-4 gap-3">
      <p className="text-[10px] text-text-muted">Day: {initial.day}</p>

      <div className="flex flex-col gap-2 min-h-[120px]">
        {messages.map((msg) =>
          msg.role === 'user' ? (
            <div key={msg.id} className="self-end max-w-[85%] rounded-lg rounded-br-sm bg-bg-surface px-3 py-1.5 text-[10px] italic text-text-primary">
              {msg.content}
            </div>
          ) : (
            <div key={msg.id} className="self-start max-w-[90%] rounded-lg rounded-bl-sm border border-border bg-white px-3 py-1.5 text-[10px] text-text-primary">
              {msg.content}
            </div>
          ),
        )}
      </div>

      <div className="relative">
        {showPlaceholder && (
          <p
            data-testid="recommend-placeholder"
            className="absolute inset-0 px-2.5 py-1.5 text-[10px] text-text-muted pointer-events-none"
          >
            Tell your assistant what you are searching for...
          </p>
        )}
        <input
          aria-label="Recommend chat input"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
          className="w-full text-[10px] border border-border rounded px-2.5 py-1.5 bg-white"
        />
      </div>
    </div>
  )
}
