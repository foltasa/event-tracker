import React from 'react'
import { renderHook, act } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useChat } from '@/hooks/useChat'
import { ChatProvider } from '@/lib/ChatContext'

vi.mock('@/lib/api', () => ({
  postChat: vi.fn(),
  getChatHistory: vi.fn().mockResolvedValue([]),
}))
import { postChat } from '@/lib/api'
import type { ChatChunk } from '@/lib/types'

const wrapper = ({ children }: { children: ReactNode }) =>
  React.createElement(ChatProvider, null, children)

describe('useChat', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts with empty messages and not streaming', () => {
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    expect(result.current.messages).toHaveLength(0)
    expect(result.current.isStreaming).toBe(false)
  })

  it('adds user message immediately on sendMessage', async () => {
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      onChunk({ type: 'done', token_usage: { input_tokens: 1, output_tokens: 1, estimated_cost_usd: 0 } })
    })
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    await act(async () => { await result.current.sendMessage('hello') })
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: 'hello' })
  })

  it('assembles streamed tokens into one assistant message', async () => {
    const chunks: ChatChunk[] = [
      { type: 'token', content: 'Hello' },
      { type: 'token', content: ' world' },
      { type: 'done', token_usage: { input_tokens: 5, output_tokens: 2, estimated_cost_usd: 0 } },
    ]
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      for (const c of chunks) onChunk(c)
    })
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    await act(async () => { await result.current.sendMessage('hi') })
    const assistantMsg = result.current.messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.content).toBe('Hello world')
  })

  it('records token usage from done chunk on last assistant message', async () => {
    const chunks: ChatChunk[] = [
      { type: 'token', content: 'Hi' },
      { type: 'done', token_usage: { input_tokens: 10, output_tokens: 3, estimated_cost_usd: 0.001 } },
    ]
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      for (const c of chunks) onChunk(c)
    })
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    await act(async () => { await result.current.sendMessage('hi') })
    const assistantMsg = result.current.messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.tokenUsage?.input_tokens).toBe(10)
  })

  it('sets error on error chunk and stops streaming', async () => {
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      onChunk({ type: 'error', message: 'rate limited' })
    })
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    await act(async () => { await result.current.sendMessage('hi') })
    expect(result.current.error).toBe('rate limited')
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.currentTool).toBeNull()
  })

  it('tracks currentTool across tool_start, tool_end, and done', async () => {
    const seenAtToolStart: (string | null)[] = []
    const seenAtToolEnd: (string | null)[] = []
    vi.mocked(postChat).mockImplementation(async (_req, onChunk) => {
      onChunk({ type: 'tool_start', tool_name: 'search_events' })
      seenAtToolStart.push('search_events')
      onChunk({ type: 'tool_end', tool_name: 'search_events', status: 'ok' })
      seenAtToolEnd.push(null)
      onChunk({ type: 'token', content: 'Done' })
      onChunk({ type: 'done', token_usage: { input_tokens: 1, output_tokens: 1, estimated_cost_usd: 0 } })
    })
    const { result } = renderHook(() => useChat('sess_1'), { wrapper })
    await act(async () => { await result.current.sendMessage('go') })
    expect(result.current.currentTool).toBeNull()
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.messages.every((m) => m.role === 'user' || m.role === 'assistant')).toBe(true)
  })
})
