'use client'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import MakeAppointmentTab, { type MakeInitial } from './MakeAppointmentTab'
import RecommendTab from './RecommendTab'

export type AppointmentModalMode = 'create' | 'edit'

export interface AppointmentModalProps {
  mode: AppointmentModalMode
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}

function Inner(props: AppointmentModalProps) {
  const [tab, setTab] = useState<'make' | 'recommend'>('make')

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') props.onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [props.onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      data-testid="appointment-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-text-primary/55 px-4"
      onClick={props.onClose}
    >
      <div
        className="relative bg-bg-page rounded-xl w-full max-w-md flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex border-b border-border bg-bg-page p-2 gap-2">
          <button
            data-testid="tab-make"
            onClick={() => setTab('make')}
            className={`flex-1 rounded px-3 py-1.5 text-xs font-semibold ${tab === 'make' ? 'bg-accent-gold text-bg-page' : 'text-text-secondary'}`}
          >Make an appointment</button>
          {props.mode === 'create' && (
            <button
              data-testid="tab-recommend"
              onClick={() => setTab('recommend')}
              className={`flex-1 rounded px-3 py-1.5 text-xs font-semibold ${tab === 'recommend' ? 'bg-accent-gold text-bg-page' : 'text-text-secondary'}`}
            >Recommend me something</button>
          )}
        </div>
        {tab === 'make' && (
          <MakeAppointmentTab
            mode={props.mode}
            initial={props.initial}
            onClose={props.onClose}
            onSaved={props.onSaved}
          />
        )}
        {tab === 'recommend' && (
          <RecommendTab initial={props.initial} />
        )}
      </div>
    </div>
  )
}

export default function AppointmentModal(props: AppointmentModalProps) {
  if (typeof document === 'undefined') return null
  return createPortal(<Inner {...props} />, document.body)
}
