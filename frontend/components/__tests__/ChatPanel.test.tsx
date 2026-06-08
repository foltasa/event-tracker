import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ChatPanel from '@/components/ChatPanel'

vi.mock('@/lib/api', () => ({ postChat: vi.fn() }))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], isStreaming: false, error: null,
    sendMessage: vi.fn(),
  })),
}))
import { useChat } from '@/hooks/useChat'
import type { LocalMessage } from '@/hooks/useChat'

describe('ChatPanel', () => {
  it('renders header', () => {
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('Chat Assistant')).toBeInTheDocument()
  })

  it('disables input while streaming', () => {
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: true, error: null, sendMessage: vi.fn(),
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByPlaceholderText(/Ask anything/)).toBeDisabled()
  })

  it('calls sendMessage on submit', async () => {
    const sendMessage = vi.fn()
    vi.mocked(useChat).mockReturnValue({
      messages: [], isStreaming: false, error: null, sendMessage,
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    const input = screen.getByPlaceholderText(/Ask anything/)
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith('hello'))
  })

  it('renders assistant messages', () => {
    const messages: LocalMessage[] = [
      { id: '1', role: 'user', content: 'hello' },
      { id: '2', role: 'assistant', content: 'Hi there!' },
    ]
    vi.mocked(useChat).mockReturnValue({
      messages, isStreaming: false, error: null, sendMessage: vi.fn(),
    })
    render(<ChatPanel sessionId="dashboard" model="gpt-4o-mini" dailyCost={0.0048} onCardClick={vi.fn()} onFeedback={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByText('hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there!')).toBeInTheDocument()
  })
})
