'use client'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import MakeAppointmentTab, { type MakeInitial } from './MakeAppointmentTab'

export type AppointmentModalMode = 'create' | 'edit'

export interface AppointmentModalProps {
  mode: AppointmentModalMode
  initial: MakeInitial
  onClose: () => void
  onSaved: () => void
}

function Inner(props: AppointmentModalProps) {
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
        <MakeAppointmentTab
          mode={props.mode}
          initial={props.initial}
          onClose={props.onClose}
          onSaved={props.onSaved}
        />
      </div>
    </div>
  )
}

export default function AppointmentModal(props: AppointmentModalProps) {
  if (typeof document === 'undefined') return null
  return createPortal(<Inner {...props} />, document.body)
}
