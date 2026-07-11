// frontend/components/CategoryFacetsSection.tsx
'use client'
import ChipInput from './ChipInput'
import type { CategoryDescriptor } from '@/lib/aboutMeCategories'
import type { CategoryFacets } from '@/lib/types'

export interface CategoryFacetsSectionProps {
  descriptor: CategoryDescriptor
  facets: CategoryFacets
  onChange: (next: CategoryFacets) => void
}

/**
 * The backend stores facet buckets as `{term: weight}` dicts for historical
 * reasons. The About Me form treats them as ordered string arrays. These two
 * helpers bridge the shapes for the ChipInput.
 */
function bucketToArray(bucket: unknown): string[] {
  if (Array.isArray(bucket)) return bucket.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
  if (bucket && typeof bucket === 'object') return Object.keys(bucket as Record<string, unknown>).filter((k) => k.trim() !== '')
  return []
}

function arrayToBucket(arr: string[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const term of arr) {
    const key = term.trim()
    if (!key) continue
    // Weight is retained on-disk for schema compatibility but has no consumer.
    out[key] = 1.0
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
              <ChipInput
                value={bucketToArray(facets[f.facetField])}
                onChange={(next) => onChange({ ...facets, [f.facetField]: arrayToBucket(next) })}
                placeholder="type and press Enter"
              />
            )}
          </label>
        ))}
      </div>
    </section>
  )
}
