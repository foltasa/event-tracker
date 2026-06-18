'use client'
import { useEffect, useState } from 'react'
import { HOUR_PX } from './HourGutter'

export default function NowLine() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])
  const minutes = now.getHours() * 60 + now.getMinutes()
  const top = (minutes / 60) * HOUR_PX
  return (
    <div
      data-testid="now-line"
      className="absolute left-0 right-0 z-20 pointer-events-none"
      style={{ top }}
    >
      <div className="absolute -left-1.5 top-[-3px] w-1.5 h-1.5 rounded-full bg-accent-gold" />
      <div className="absolute left-0 right-0 h-[1px] bg-accent-gold" />
    </div>
  )
}
