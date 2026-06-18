import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AppointmentModal from '@/components/calendar/appointmentModal/AppointmentModal'
import * as api from '@/lib/api'

vi.mock('@/lib/api', async () => ({
  createAppointment: vi.fn().mockResolvedValue({}),
  updateAppointment: vi.fn().mockResolvedValue({}),
  deleteAppointment: vi.fn().mockResolvedValue(undefined),
  recommendAppointment: vi.fn().mockResolvedValue({ message: 'Currently not implemented' }),
}))

describe('AppointmentModal — Make tab', () => {
  it('shows Save but not Delete in create mode', () => {
    render(<AppointmentModal
      mode="create"
      initial={{ day: '2026-06-16', start_at: null, end_at: null, title: '' }}
      onClose={() => {}}
      onSaved={() => {}}
    />)
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
  })

  it('shows Delete in edit mode', () => {
    render(<AppointmentModal
      mode="edit"
      initial={{
        id: 'app-1', day: '2026-06-16',
        start_at: '2026-06-16T09:00:00Z', end_at: '2026-06-16T10:00:00Z',
        title: 'Standup',
      }}
      onClose={() => {}}
      onSaved={() => {}}
    />)
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
  })

  it('calls createAppointment on Save in create mode', async () => {
    const onSaved = vi.fn()
    render(<AppointmentModal
      mode="create"
      initial={{ day: '2026-06-16', start_at: null, end_at: null, title: '' }}
      onClose={() => {}}
      onSaved={onSaved}
    />)
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'New' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /all day/i }))
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    // microtask flush:
    await Promise.resolve()
    await Promise.resolve()
    expect(api.createAppointment).toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalled()
  })
})
