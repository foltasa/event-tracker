'use client'
import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from 'react'
import { deleteChatHistory, getChatHistory, postChat } from '@/lib/api'
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
  ensureHydrated: (sessionId: string) => void
  clearSession: (sessionId: string) => Promise<void>
}

const ChatCtx = createContext<ChatCtxValue | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<Record<string, SessionState>>({})
  // Tracks which sessions we've already requested history for, so the same
  // useChatSession hook firing on multiple mounts doesn't refetch.
  const [hydrated, setHydrated] = useState<Set<string>>(new Set())

  const update = useCallback((sessionId: string, fn: (s: SessionState) => SessionState) => {
    setSessions((all) => ({ ...all, [sessionId]: fn(all[sessionId] ?? EMPTY) }))
  }, [])

  const ensureHydrated = useCallback((sessionId: string) => {
    let alreadyMarked = false
    setHydrated((s) => {
      if (s.has(sessionId)) { alreadyMarked = true; return s }
      const next = new Set(s)
      next.add(sessionId)
      return next
    })
    if (alreadyMarked) return

    void (async () => {
      try {
        const msgs = await getChatHistory(sessionId)
        if (msgs.length === 0) return
        const localMessages: LocalMessage[] = msgs
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({
            id: m.id,
            role: m.role as 'user' | 'assistant',
            content: m.content,
            tokenUsage: m.token_usage ?? undefined,
          }))
        setSessions((all) => {
          // If the user has already started a new message locally before the
          // server response arrived, don't clobber that in-progress state.
          const existing = all[sessionId] ?? EMPTY
          if (existing.messages.length > 0) return all
          return { ...all, [sessionId]: { ...EMPTY, messages: localMessages } }
        })
      } catch {
        // Allow a retry on the next mount if the fetch failed.
        setHydrated((s) => { const n = new Set(s); n.delete(sessionId); return n })
      }
    })()
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

  const clearSession = useCallback(async (sessionId: string) => {
    await deleteChatHistory(sessionId)
    setSessions((all) => ({ ...all, [sessionId]: EMPTY }))
    // Drop the hydrated marker so a future remount can refetch (it would
    // return an empty list, but this keeps the data path consistent).
    setHydrated((s) => { const n = new Set(s); n.delete(sessionId); return n })
  }, [])

  return (
    <ChatCtx.Provider value={{ sessions, sendMessage, ensureHydrated, clearSession }}>{children}</ChatCtx.Provider>
  )
}

function useChatCtx(): ChatCtxValue {
  const ctx = useContext(ChatCtx)
  if (!ctx) throw new Error('ChatContext must be used within ChatProvider')
  return ctx
}

export function useChatSession(sessionId: string) {
  const ctx = useChatCtx()
  useEffect(() => { ctx.ensureHydrated(sessionId) }, [sessionId, ctx])
  const session = ctx.sessions[sessionId] ?? EMPTY
  return {
    ...session,
    sendMessage: (text: string) => ctx.sendMessage(sessionId, text),
    clearSession: () => ctx.clearSession(sessionId),
  }
}
