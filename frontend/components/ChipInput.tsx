'use client'
import { useState, KeyboardEvent } from 'react'

export interface ChipInputProps {
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}

function isDuplicate(existing: string[], candidate: string): boolean {
  const c = candidate.toLowerCase()
  return existing.some((e) => e.toLowerCase() === c)
}

export default function ChipInput({ value, onChange, placeholder }: ChipInputProps) {
  const [draft, setDraft] = useState('')

  function commit(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    if (isDuplicate(value, trimmed)) {
      setDraft('')
      return
    }
    onChange([...value, trimmed])
    setDraft('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      commit(draft)
      return
    }
    if (e.key === 'Backspace' && draft === '' && value.length > 0) {
      e.preventDefault()
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded border border-border bg-white px-2 py-1 text-[13px]">
      {value.map((chip, idx) => (
        <span
          key={`${chip}-${idx}`}
          className="inline-flex items-center gap-1 rounded bg-bg-page px-2 py-0.5 text-[12px] text-text-primary"
        >
          {chip}
          <button
            type="button"
            aria-label={`remove ${chip}`}
            className="text-text-muted hover:text-text-primary"
            onClick={() => onChange(value.filter((_, i) => i !== idx))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        className="flex-1 min-w-[6ch] border-0 bg-transparent p-0 text-[13px] focus:outline-none"
        placeholder={placeholder}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => commit(draft)}
      />
    </div>
  )
}
