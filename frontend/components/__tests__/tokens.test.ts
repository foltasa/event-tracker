import config from '@/tailwind.config'

describe('tailwind config', () => {
  const colors = (config.theme?.extend as any)?.colors

  const expectedTokens: Record<string, string> = {
    'bg-page':           '#faf7f2',
    'bg-surface':        '#f0ebe2',
    'bg-chat':           '#fdf9f4',
    'accent-gold':       '#92763c',
    'accent-gold-light': '#f5ede0',
    'text-primary':      '#1a1208',
    'text-secondary':    '#6b5c3e',
    'text-muted':        '#b0956b',
    'border':            '#e8e0d4',
    'border-active':     '#92763c',
  }

  it.each(Object.entries(expectedTokens))('token %s = %s', (token, value) => {
    expect(colors?.[token]).toBe(value)
  })
})
