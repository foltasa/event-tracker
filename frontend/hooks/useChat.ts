'use client'
import { useState, useCallback } from 'react'
import { postChat } from '@/lib/api'
import type { ChatTokenUsage } from '@/lib/types'

export interface LocalMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  toolName?: string
  tokenUsage?: ChatTokenUsage
  isStreaming?: boolean
}

interface ChatState {
  messages: LocalMessage[]
  isStreaming: boolean
  error: string | null
}

export function useChat(sessionId: string) {
  const [state, setState] = useState<ChatState>({
    messages: [], isStreaming: false, error: null,
  })

  const sendMessage = useCallback(async (text: string) => {
    const userMsg: LocalMessage = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    const assistantMsg: LocalMessage = { id: assistantId, role: 'assistant', content: '', isStreaming: true }

    setState((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
      error: null,
    }))

    await postChat({ message: text, session_id: sessionId }, (chunk) => {
      if (chunk.type === 'token') {
        setState((s) => ({
          ...s,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + chunk.content } : m
          ),
        }))
      } else if (chunk.type === 'tool_start') {
        const toolMsg: LocalMessage = {
          id: crypto.randomUUID(), role: 'tool', content: '', toolName: chunk.tool_name,
        }
        setState((s) => ({ ...s, messages: [...s.messages, toolMsg] }))
      } else if (chunk.type === 'done') {
        setState((s) => ({
          ...s,
          isStreaming: false,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false, tokenUsage: chunk.token_usage } : m
          ),
        }))
      } else if (chunk.type === 'error') {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: chunk.message,
          messages: s.messages.map((m) =>
            m.id === assistantId ? { ...m, isStreaming: false } : m
          ),
        }))
      }
    })
  }, [sessionId])

  return { ...state, sendMessage }
}
