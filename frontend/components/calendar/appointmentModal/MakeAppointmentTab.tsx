'use client'
import { useState } from 'react'
import { createAppointment, deleteAppointment, updateAppointment } from '@/lib/api'

export interface MakeInitial {
  id?: string
  day: string                       // YYYY-MM-DD
  title?: string
  start_at?: string | null
  end_at?: string | null
}

function isoToTimeInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function timeInputToIso(day: string, hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const [y, mo, d] = day.split('-').map(Number)
  return new Date(y, mo - 1, d, h, m).toISOString()
}

export default function MakeAppointmentTab({
  mode, initial, onClose, onSaved,
}: {
  mode: 'create' | 'edit'
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}) {
  const [title, setTitle] = useState(initial.title ?? '')
  const [allDay, setAllDay] = useState(initial.start_at == null && initial.end_at == null)
  const [start, setStart] = useState(isoToTimeInput(initial.start_at))
  const [end, setEnd] = useState(isoToTimeInput(initial.end_at))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const canSave = title.trim().length > 0 && !busy

  async function handleSave() {
    setError(null)
    if (!allDay && start && end && end <= start) {
      setError('End time must be after start time.')
      return
    }
    const payload = {
      title: title.trim(),
      day: initial.day,
      start_at: allDay || !start ? null : timeInputToIso(initial.day, start),
      end_at: allDay || !end ? null : timeInputToIso(initial.day, end),
    }
    setBusy(true)
    try {
      if (mode === 'edit' && initial.id) {
        await updateAppointment(initial.id, payload)
      } else {
        await createAppointment(payload)
      }
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!initial.id) return
    if (!window.confirm('Delete this appointment?')) return
    setBusy(true)
    try {
      await deleteAppointment(initial.id)
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <label className="text-[12px] text-text-secondary">
        Title
        <input
          autoFocus={mode === 'create'}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white"
        />
      </label>

      <label className="flex items-center gap-2 text-[12px] text-text-secondary">
        <input
          type="checkbox"
          checked={allDay}
          onChange={(e) => setAllDay(e.target.checked)}
        />
        All day
      </label>

      {!allDay && (
        <div className="flex gap-2">
          <label className="flex-1 text-[12px] text-text-secondary">
            Start
            <input
              type="time"
              step={900}
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white"
            />
          </label>
          <label className="flex-1 text-[12px] text-text-secondary">
            End
            <input
              type="time"
              step={900}
              value={end}
              disabled={!start}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-1 w-full text-xs border border-border rounded px-2 py-1.5 bg-white disabled:bg-bg-surface"
            />
            <span className="block mt-0.5 text-[10px] text-text-muted">Leave empty to last until end of day.</span>
          </label>
        </div>
      )}

      <p className="text-[11px] text-text-muted">Day: {initial.day}</p>

      {error && <p className="text-[11px] text-red-500">{error}</p>}

      <div className="flex justify-between pt-2 border-t border-border">
        <div>
          {mode === 'edit' && (
            <button
              onClick={handleDelete}
              disabled={busy}
              className="text-xs text-red-500 hover:underline disabled:opacity-50"
            >Delete</button>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={!canSave}
          className="bg-accent-gold text-bg-page rounded px-4 py-1.5 text-xs font-semibold disabled:opacity-50"
        >Save</button>
      </div>
    </div>
  )
}
