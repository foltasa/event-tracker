'use client'
import { useChatSession, type LocalMessage } from '@/lib/ChatContext'

export type { LocalMessage }

// Hook kept for API compatibility. Per-session state lives in the ChatProvider
// mounted in the AppShell so it persists across page navigation.
export function useChat(sessionId: string) {
  return useChatSession(sessionId)
}
