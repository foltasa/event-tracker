import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import TopNav from '@/components/TopNav'

vi.mock('next/link', () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}))

describe('TopNav', () => {
  it('renders brand name', () => {
    render(<TopNav active="timetable" date="Hamburg · June 8" />)
    expect(screen.getByText('SlotIn')).toBeInTheDocument()
  })

  it('applies active style to current page link', () => {
    render(<TopNav active="timetable" date="Hamburg · June 8" />)
    expect(screen.getByText('Timetable')).toHaveClass('bg-accent-gold')
  })

  it('does not apply active style to inactive links', () => {
    render(<TopNav active="timetable" date="Hamburg · June 8" />)
    expect(screen.getByText('Explore')).not.toHaveClass('bg-accent-gold')
  })

  it('renders date string', () => {
    render(<TopNav active="timetable" date="Hamburg · June 8" />)
    expect(screen.getByText('Hamburg · June 8')).toBeInTheDocument()
  })

  it('does not render a Settings link', () => {
    render(<TopNav active="timetable" date="Hamburg · June 8" />)
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
  })
})
