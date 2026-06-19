import Link from 'next/link'

type ActivePage = 'dashboard' | 'calendar' | 'settings'

const LINKS: { href: string; label: string; page: ActivePage }[] = [
  { href: '/',          label: 'Dashboard', page: 'dashboard' },
  { href: '/calendar',  label: 'Calendar',  page: 'calendar'  },
  { href: '/settings',  label: 'Settings',  page: 'settings'  },
]

export default function TopNav({ active, date }: { active: ActivePage; date: string }) {
  return (
    <nav className="sticky top-0 z-30 flex items-center gap-1 px-5 py-2.5 bg-bg-surface border-b border-border">
      <span className="font-serif font-bold text-base text-text-primary mr-5">
        SlotIn
      </span>
      {LINKS.map(({ href, label, page }) => (
        <Link
          key={page}
          href={href}
          className={
            page === active
              ? 'rounded px-3 py-1 text-xs font-semibold bg-accent-gold text-bg-page'
              : 'rounded px-3 py-1 text-xs text-text-secondary hover:text-text-primary'
          }
        >
          {label}
        </Link>
      ))}
      <span className="ml-auto text-xs italic text-accent-gold">{date}</span>
    </nav>
  )
}
