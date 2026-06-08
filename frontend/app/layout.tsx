import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import SWRProvider from '@/lib/swr-provider'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Event Tracker',
  description: 'Personalized Hamburg event recommendations',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <SWRProvider>{children}</SWRProvider>
      </body>
    </html>
  )
}
