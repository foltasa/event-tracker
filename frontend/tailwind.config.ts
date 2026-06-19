import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
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
      },
      fontFamily: {
        serif: ['Georgia', 'serif'],
      },
      fontSize: {
        // 10% larger than Tailwind defaults (min +1px) so the app matches the
        // 110%-zoom level it was visually tuned at.
        xs:   ['13px', { lineHeight: '1.4' }],
        sm:   ['15px', { lineHeight: '1.45' }],
        base: ['18px', { lineHeight: '1.6' }],
        lg:   ['20px', { lineHeight: '1.6' }],
        xl:   ['22px', { lineHeight: '1.55' }],
        '2xl':['26px', { lineHeight: '1.5' }],
        '3xl':['33px', { lineHeight: '1.4' }],
      },
    },
  },
  plugins: [],
}
export default config
