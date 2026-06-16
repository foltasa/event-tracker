'use client'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { postChat } from '@/lib/api'
import type { ChatTokenUsage } from '@/lib/types'

export interface LocalMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tokenUsage?: ChatTokenUsage
  isStreaming?: boolean
}

export interface SessionState {
  messages: LocalMessage[]
  isStreaming: boolean
  currentTool: string | null
  error: string | null
}

const EMPTY: SessionState = { messages: [], isStreaming: false, currentTool: null, error: null }

interface ChatCtxValue {
  sessions: Record<string, SessionState>
  sendMessage: (sessionId: string, text: string) => Promise<void>
}

const ChatCtx = createContext<ChatCtxValue | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<Record<string, SessionState>>({})

  const update = useCallback((sessionId: string, fn: (s: SessionState) => SessionState) => {
    setSessions((all) => ({ ...all, [sessionId]: fn(all[sessionId] ?? EMPTY) }))
  }, [])

  const sendMessage = useCallback(async (sessionId: string, text: string) => {
    const userMsg: LocalMessage = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    const assistantMsg: LocalMessage = { id: assistantId, role: 'assistant', content: '', isStreaming: true }

    update(sessionId, (s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
      currentTool: null,
      error: null,
    }))

    await postChat({ message: text, session_id: sessionId }, (chunk) => {
      if (chunk.type === 'token') {
        update(sessionId, (s) => ({
          ...s,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + chunk.content } : m
          ),
        }))
      } else if (chunk.type === 'tool_start') {
        update(sessionId, (s) => ({ ...s, currentTool: chunk.tool_name }))
      } else if (chunk.type === 'tool_end') {
        update(sessionId, (s) => ({ ...s, currentTool: null }))
      } else if (chunk.type === 'done') {
        update(sessionId, (s) => ({
          ...s,
          isStreaming: false,
          currentTool: null,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false, tokenUsage: chunk.token_usage } : m
          ),
        }))
      } else if (chunk.type === 'error') {
        update(sessionId, (s) => ({
          ...s,
          isStreaming: false,
          currentTool: null,
          error: chunk.message,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false } : m
          ),
        }))
      }
    })
  }, [update])

  return <ChatCtx.Provider value={{ sessions, sendMessage }}>{children}</ChatCtx.Provider>
}

function useChatCtx(): ChatCtxValue {
  const ctx = useContext(ChatCtx)
  if (!ctx) throw new Error('ChatContext must be used within ChatProvider')
  return ctx
}

export function useChatSession(sessionId: string) {
  const ctx = useChatCtx()
  const session = ctx.sessions[sessionId] ?? EMPTY
  return {
    ...session,
    sendMessage: (text: string) => ctx.sendMessage(sessionId, text),
  }
}
