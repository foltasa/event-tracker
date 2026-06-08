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
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Event Tracker')).toBeInTheDocument()
  })

  it('applies active style to current page link', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    const dashLink = screen.getByText('Dashboard')
    expect(dashLink).toHaveClass('bg-accent-gold')
  })

  it('does not apply active style to inactive links', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Calendar')).not.toHaveClass('bg-accent-gold')
  })

  it('renders date string', () => {
    render(<TopNav active="dashboard" date="Hamburg · June 8" />)
    expect(screen.getByText('Hamburg · June 8')).toBeInTheDocument()
  })
})
