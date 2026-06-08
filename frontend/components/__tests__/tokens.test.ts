import config from '@/tailwind.config'

describe('tailwind config', () => {
  it('exposes accent-gold token', () => {
    const colors = (config.theme?.extend as any)?.colors
    expect(colors?.['accent-gold']).toBe('#92763c')
  })
  it('exposes bg-page token', () => {
    const colors = (config.theme?.extend as any)?.colors
    expect(colors?.['bg-page']).toBe('#faf7f2')
  })
})
