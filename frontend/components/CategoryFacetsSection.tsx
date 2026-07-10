// frontend/components/CategoryFacetsSection.tsx
'use client'
import type { CategoryDescriptor } from '@/lib/aboutMeCategories'
import type { CategoryFacets } from '@/lib/types'

export interface CategoryFacetsSectionProps {
  descriptor: CategoryDescriptor
  facets: CategoryFacets
  onChange: (next: CategoryFacets) => void
}

function bucketToText(bucket: Record<string, number> | undefined): string {
  if (!bucket) return ''
  return Object.keys(bucket).join(', ')
}

function textToBucket(text: string, weight = 0.8): Record<string, number> {
  const out: Record<string, number> = {}
  for (const raw of text.split(',')) {
    const key = raw.trim()
    if (!key) continue
    out[key] = weight
  }
  return out
}

export default function CategoryFacetsSection({ descriptor, facets, onChange }: CategoryFacetsSectionProps) {
  return (
    <section className="rounded-lg border border-border bg-white p-4">
      <h3 className="font-serif font-bold text-[15px] text-text-primary mb-3">
        {descriptor.displayName}
      </h3>
      <div className="flex flex-col gap-3">
        {descriptor.fields.map((f) => (
          <label key={f.label} className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-text-primary">{f.label}</span>
            {f.helper ? (
              <span className="text-[11px] text-text-muted">{f.helper}</span>
            ) : null}
            {f.facetField === 'notes' ? (
              <textarea
                className="rounded border border-border px-2 py-1 text-[13px]"
                rows={3}
                value={facets.notes ?? ''}
                onChange={(e) => onChange({ ...facets, notes: e.target.value })}
              />
            ) : (
              <input
                type="text"
                className="rounded border border-border px-2 py-1 text-[13px]"
                value={bucketToText(facets[f.facetField] as Record<string, number> | undefined)}
                onChange={(e) =>
                  onChange({ ...facets, [f.facetField]: textToBucket(e.target.value) })
                }
              />
            )}
          </label>
        ))}
      </div>
    </section>
  )
}
