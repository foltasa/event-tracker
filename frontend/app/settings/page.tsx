'use client'
import useSWR, { useSWRConfig } from 'swr'
import { getProfile, updateProfileSettings } from '@/lib/api'
import type { UserProfileResponse } from '@/lib/types'

export default function SettingsPage() {
  const { mutate } = useSWRConfig()
  const { data: profile, isLoading } = useSWR<UserProfileResponse>('/profile', getProfile)

  async function onToggleAutoRec(next: boolean) {
    const updated = await updateProfileSettings({ auto_recommendations_enabled: next })
    mutate('/profile', updated, { revalidate: false })
  }

  return (
    <main className="flex-1 overflow-y-auto px-6 py-6 bg-bg-page">
      <h1 className="font-serif font-bold text-lg text-text-primary mb-4">Settings</h1>
      <section className="rounded-lg border border-border bg-white p-4 max-w-xl">
        <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">AI Assistant</h2>
        {isLoading || !profile ? (
          <p className="text-[12px] text-text-muted">Loading…</p>
        ) : (
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              aria-label="Add recommendations to my timetable automatically"
              checked={profile.settings.auto_recommendations_enabled}
              onChange={(e) => onToggleAutoRec(e.target.checked)}
              className="mt-1 h-4 w-4 accent-accent-gold"
            />
            <span className="flex flex-col">
              <span className="text-[13px] font-semibold text-text-primary">
                Add recommendations to my timetable automatically
              </span>
              <span className="text-[11px] text-text-muted mt-0.5">
                When on, events the AI assistant mentions appear in your timetable as gray
                &quot;Recommendation&quot; blocks until you slot them in or out.
              </span>
            </span>
          </label>
        )}
      </section>
    </main>
  )
}
