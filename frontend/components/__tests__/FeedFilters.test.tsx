import { render, screen, fireEvent } from '@testing-library/react'
import FeedFilters from '@/components/FeedFilters'
import type { FeedFilterState } from '@/components/FeedFilters'
import { describe, it, expect, vi } from 'vitest'

const defaultFilters: FeedFilterState = {
  category: null, datePreset: 'any', q: '',
}

describe('FeedFilters', () => {
  it('renders All chip as active by default', () => {
    render(<FeedFilters filters={defaultFilters} onChange={vi.fn()} />)
    expect(screen.getByText('Alle')).toHaveClass('bg-accent-gold')
  })

  it('calls onChange with new category when chip clicked', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={defaultFilters} onChange={onChange} />)
    fireEvent.click(screen.getByText('Konzerte'))
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, category: 'concerts' })
  })

  it('calls onChange with null category when All clicked', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={{ ...defaultFilters, category: 'concerts' }} onChange={onChange} />)
    fireEvent.click(screen.getByText('Alle'))
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, category: null })
  })

  it('calls onChange with updated datePreset when dropdown changed', () => {
    const onChange = vi.fn()
    render(<FeedFilters filters={defaultFilters} onChange={onChange} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'this-week' } })
    expect(onChange).toHaveBeenCalledWith({ ...defaultFilters, datePreset: 'this-week' })
  })
})
