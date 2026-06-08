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
        'border-warm':       '#e8e0d4',
        'border-active':     '#92763c',
      },
      fontFamily: {
        serif: ['Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
export default config
