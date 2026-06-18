import { render, screen, fireEvent } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import RecommendTab from '@/components/calendar/appointmentModal/RecommendTab'
import * as api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  recommendAppointment: vi.fn().mockResolvedValue({ message: 'Currently not implemented' }),
}))

describe('RecommendTab', () => {
  const baseInitial = { day: '2026-06-16', start_at: null, end_at: null, title: '' }

  it('shows placeholder text when empty, unfocused, and no messages sent', () => {
    render(<RecommendTab initial={baseInitial} />)
    expect(screen.getByText(/Tell your assistant what you are searching for/i)).toBeInTheDocument()
  })

  it('hides placeholder when input focused', () => {
    render(<RecommendTab initial={baseInitial} />)
    fireEvent.focus(screen.getByRole('textbox'))
    expect(screen.queryByText(/Tell your assistant what you are searching for/i)).not.toBeInTheDocument()
  })

  it('after sending a message, placeholder never returns', async () => {
    render(<RecommendTab initial={baseInitial} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'help' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(api.recommendAppointment).toHaveBeenCalled()
    expect(await screen.findByText(/Currently not implemented/i)).toBeInTheDocument()
    fireEvent.blur(input)
    expect(screen.queryByText(/Tell your assistant what you are searching for/i)).not.toBeInTheDocument()
  })
})
