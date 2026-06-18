import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import WeekView from '@/components/calendar/WeekView'

const baseAppointment = {
  id: 'app-1', title: 'Turing', day: '2026-06-16',
  start_at: '2026-06-16T07:00:00Z', end_at: '2026-06-16T14:30:00Z',
  created_at: '2026-06-16T00:00:00Z',
}

describe('WeekView', () => {
  it('renders a block for an appointment', () => {
    render(<WeekView
      weekStart={new Date(2026, 5, 15)}     // Mon June 15 2026
      todayKey="2026-06-16"
      appointments={[baseAppointment]}
      events={[]}
      onPrev={() => {}}
      onNext={() => {}}
      onToday={() => {}}
      onEmptyClick={() => {}}
      onItemClick={() => {}}
      onAllDayClick={() => {}}
    />)
    expect(screen.getByTestId('event-block-app-1')).toBeInTheDocument()
  })

  it('fires onItemClick when an appointment is clicked', () => {
    const onItemClick = vi.fn()
    render(<WeekView
      weekStart={new Date(2026, 5, 15)}
      todayKey="2026-06-16"
      appointments={[baseAppointment]}
      events={[]}
      onPrev={() => {}}
      onNext={() => {}}
      onToday={() => {}}
      onEmptyClick={() => {}}
      onItemClick={onItemClick}
      onAllDayClick={() => {}}
    />)
    fireEvent.click(screen.getByTestId('event-block-app-1'))
    expect(onItemClick).toHaveBeenCalledOnce()
    expect(onItemClick.mock.calls[0][0].id).toBe('app-1')
  })
})
