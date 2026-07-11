// frontend/app/about-me/page.tsx
'use client'
import { useEffect, useMemo, useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import CategoryFacetsSection from '@/components/CategoryFacetsSection'
import { getAboutMe, updateAboutMe } from '@/lib/api'
import { CATEGORY_DESCRIPTORS, SELECTABLE_CATEGORIES } from '@/lib/aboutMeCategories'
import type { AboutMeResponse, CategoryFacets, EventCategory } from '@/lib/types'

export default function AboutMePage() {
  const { mutate } = useSWRConfig()
  const { data, isLoading } = useSWR<AboutMeResponse>('/about-me', getAboutMe)

  const [active, setActive] = useState<EventCategory[]>([])
  const [facets, setFacets] = useState<Partial<Record<EventCategory, CategoryFacets>>>({})
  const [aboutMe, setAboutMe] = useState<string>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!data) return
    setActive((data.active_categories ?? []) as EventCategory[])
    setFacets(data.taste_facets ?? {})
    setAboutMe(data.about_me ?? '')
  }, [data])

  const isFirstVisit = data?.active_categories === null

  function toggleCategory(cat: EventCategory) {
    setActive((prev) => (prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]))
  }

  function updateFacetsFor(cat: EventCategory, next: CategoryFacets) {
    setFacets((prev) => ({ ...prev, [cat]: next }))
  }

  async function onSave() {
    setSaving(true)
    try {
      const updated = await updateAboutMe({
        active_categories: active,
        taste_facets: facets,
        about_me: aboutMe,
      })
      mutate('/about-me', updated, { revalidate: false })
    } finally {
      setSaving(false)
    }
  }

  const sortedActive = useMemo(
    () => SELECTABLE_CATEGORIES.filter((c) => active.includes(c)),
    [active],
  )

  return (
    <main className="flex-1 overflow-y-auto px-6 py-6 bg-bg-page">
      <h1 className="font-serif font-bold text-lg text-text-primary mb-1">About Me</h1>
      <p className="text-[12px] text-text-muted mb-4">
        Tell the assistant which categories interest you and what you like in each.
        You can update this at any time.
      </p>
      {isFirstVisit ? (
        <div className="mb-4 rounded border border-accent-gold bg-white p-3 text-[12px] text-text-primary">
          Before the assistant can suggest anything, pick at least one category below.
        </div>
      ) : null}

      {isLoading || !data ? (
        <p className="text-[12px] text-text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-4 max-w-2xl">
          <section className="rounded-lg border border-border bg-white p-4">
            <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">
              Categories
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {SELECTABLE_CATEGORIES.map((cat) => (
                <label key={cat} className="flex items-center gap-2 text-[13px] text-text-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-accent-gold"
                    checked={active.includes(cat)}
                    onChange={() => toggleCategory(cat)}
                  />
                  {CATEGORY_DESCRIPTORS[cat].displayName}
                </label>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-white p-4">
            <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">
              General
            </h2>
            <p className="text-[11px] text-text-muted mb-2">
              Anything the assistant should know that isn't category-specific.
            </p>
            <textarea
              className="w-full rounded border border-border px-2 py-1 text-[13px]"
              rows={6}
              value={aboutMe}
              onChange={(e) => setAboutMe(e.target.value)}
            />
          </section>

          {sortedActive.map((cat) => (
            <CategoryFacetsSection
              key={cat}
              descriptor={CATEGORY_DESCRIPTORS[cat]}
              facets={facets[cat] ?? {}}
              onChange={(next) => updateFacetsFor(cat, next)}
            />
          ))}

          <div className="flex gap-2">
            <button
              onClick={onSave}
              disabled={saving}
              className="rounded bg-accent-gold px-4 py-2 text-[13px] font-semibold text-bg-page disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
