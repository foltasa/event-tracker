import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ChatPanel from '@/components/ChatPanel'

vi.mock('@/lib/api', () => ({ postChat: vi.fn() }))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], isStreaming: false, error: null,
    sendMessage: vi.fn(), clearSession: vi.fn(),
  })),
}))
import { useChat } from '@/hooks/useChat'
import type { LocalMessage } from '@/hooks/useChat'

describe('ChatPanel', () => {
  it('renders header', () => {
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Chat Assistant')).toBeInTheDocument()
  })

  it('disables the message input', () => {
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByPlaceholderText(/Ask anything/)).toBeDisabled()
  })

  it('calls clearSession when the Delete chat button is clicked and confirmed', async () => {
    const clearSession = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: false, error: null, sendMessage: vi.fn(), clearSession,
    } as any)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /delete chat/i }))
    await waitFor(() => expect(clearSession).toHaveBeenCalledOnce())
  })

  it('renders assistant messages', () => {
    const messages: LocalMessage[] = [
      { id: '1', role: 'user', content: 'hello' },
      { id: '2', role: 'assistant', content: 'Hi there!' },
    ]
    vi.mocked(useChat).mockReturnValue({
      messages, isStreaming: false, error: null, sendMessage: vi.fn(),
    })
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there!')).toBeInTheDocument()
  })

  it('does not show the model name or token usage in the header', () => {
    render(<ChatPanel sessionId="dashboard" onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.queryByText(/gpt-4o-mini/)).not.toBeInTheDocument()
    expect(screen.queryByText(/today/)).not.toBeInTheDocument()
  })
})
