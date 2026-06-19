'use client'
import type { DigestPick, EventWithContext, Sentiment } from '@/lib/types'

type FeedOrMini = { variant: 'feed' | 'chat-mini'; data: EventWithContext }
type DigestVariant = { variant: 'digest'; data: DigestPick }
type Props = (FeedOrMini | DigestVariant) & {
  onCardClick: (id: string) => void
  // `sentiment === null` means "clear feedback".
  onFeedback: (id: string, sentiment: Sentiment | null) => void
  // `save === false` means "unsave".
  onSave: (id: string, save: boolean) => void
  // Optimistic overrides from the AppShell while a write is in-flight. `undefined`
  // means "no override, trust the cached value on the event/context".
  forceSaved?: boolean
  forceSentiment?: Sentiment | null
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-DE', {
    weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatPrice(min: number | null, max: number | null, isFree: boolean) {
  if (isFree) return 'Free'
  if (min == null) return ''
  if (max != null && max !== min) return `€${min}–${max}`
  return `€${min}`
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider font-semibold bg-accent-gold text-bg-page">
      {category}
    </span>
  )
}

function FeedbackButtons({
  id, sentiment, onFeedback, disabled,
}: {
  id: string
  sentiment: Sentiment | null
  onFeedback: (id: string, s: Sentiment | null) => void
  disabled: boolean
}) {
  return (
    <>
      <button
        aria-label="Like"
        disabled={disabled}
        onClick={(e) => { e.stopPropagation(); onFeedback(id, sentiment === 'like' ? null : 'like') }}
        className={`rounded border px-1.5 py-0.5 text-xs ${sentiment === 'like' ? 'bg-accent-gold border-accent-gold text-bg-page' : 'bg-white border-border'}`}
      >
        👍
      </button>
      <button
        aria-label="Dislike"
        disabled={disabled}
        onClick={(e) => { e.stopPropagation(); onFeedback(id, sentiment === 'dislike' ? null : 'dislike') }}
        className={`rounded border px-1.5 py-0.5 text-xs ${sentiment === 'dislike' ? 'bg-text-secondary border-text-secondary text-bg-page' : 'bg-white border-border'}`}
      >
        👎
      </button>
    </>
  )
}

export default function EventCard({
  variant, data, onCardClick, onFeedback, onSave, forceSaved, forceSentiment,
}: Props) {
  const event = variant === 'digest' ? (data as DigestPick).event : (data as EventWithContext)
  const ctx   = variant !== 'digest' ? (data as EventWithContext) : null
  const justification = variant === 'digest' ? (data as DigestPick).justification : null

  const isActive   = event.is_active
  const sentiment: Sentiment | null =
    forceSentiment !== undefined ? forceSentiment : (ctx?.user_sentiment ?? null)
  const isSaved    = forceSaved !== undefined ? forceSaved : (ctx?.is_saved ?? false)
  const priceStr   = formatPrice(event.price_min, event.price_max, event.is_free)
  const dateStr    = formatDate(event.start_datetime)

  const borderClass = sentiment === 'like' ? 'border-border-active' : 'border-border'
  const opacityClass = isActive ? '' : 'opacity-50 pointer-events-none'

  const imageBanner = (height: string) => (
    <div
      className={`relative ${height} flex-shrink-0 cursor-pointer`}
      style={event.image_url
        ? { backgroundImage: `url(${event.image_url})`, backgroundSize: 'cover', backgroundPosition: 'center' }
        : { background: 'linear-gradient(135deg, #d4b896, #b8906a)' }
      }
      onClick={() => isActive && onCardClick(event.id)}
    >
      <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/50" />
      <div className="absolute bottom-1 left-1.5">
        <CategoryBadge category={event.category} />
      </div>
    </div>
  )

  if (variant === 'digest') {
    return (
      <div className={`min-w-[160px] rounded-lg border ${borderClass} ${opacityClass} overflow-hidden flex-shrink-0 bg-white`}>
        {imageBanner('h-[60px]')}
        <div className="p-2">
          <button
            className="font-serif text-[11px] font-bold text-text-primary text-left w-full"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary mt-0.5">
            {dateStr}{priceStr && ` · ${priceStr}`}
          </p>
          {justification && (
            <p className="text-[9px] italic text-text-primary mt-1 line-clamp-2">{justification}</p>
          )}
          <div className="flex gap-1 mt-1.5 items-center">
            <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
            <button
              onClick={(e) => { e.stopPropagation(); onSave(event.id, !isSaved) }}
              className="ml-auto rounded bg-accent-gold text-bg-page text-[9px] px-1.5 py-0.5"
            >
              {isSaved ? 'Slot Out' : 'Slot in'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (variant === 'chat-mini') {
    return (
      <div className={`rounded-lg border ${borderClass} ${opacityClass} overflow-hidden bg-bg-page w-full`}>
        {imageBanner('h-9')}
        <div className="p-1.5">
          <button
            className="font-serif text-[10px] font-bold text-text-primary text-left w-full"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary">{dateStr}{priceStr && ` · ${priceStr}`}</p>
          <div className="flex gap-1 mt-1">
            <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
            <button
              onClick={(e) => { e.stopPropagation(); onSave(event.id, !isSaved) }}
              className="ml-auto rounded bg-accent-gold text-bg-page text-[8px] px-1.5 py-0.5"
            >
              {isSaved ? 'Slot Out' : 'Slot in'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // variant === 'feed'
  return (
    <div className={`flex h-[68px] flex-shrink-0 rounded-lg border ${borderClass} ${opacityClass} overflow-hidden bg-white`}>
      {imageBanner('w-20')}
      <div className="flex-1 flex flex-col justify-between p-2 min-w-0">
        <div>
          <button
            className="font-serif text-[11px] font-bold text-text-primary text-left w-full truncate"
            onClick={() => isActive && onCardClick(event.id)}
          >
            {event.title}
          </button>
          <p className="text-[9px] text-text-secondary">
            {event.venue_name && `${event.venue_name} · `}{dateStr}{priceStr && ` · ${priceStr}`}
          </p>
        </div>
        <div className="flex gap-1 items-center">
          <FeedbackButtons id={event.id} sentiment={sentiment} onFeedback={onFeedback} disabled={!isActive} />
          <button
            onClick={(e) => { e.stopPropagation(); onSave(event.id, !isSaved) }}
            className="ml-auto rounded bg-accent-gold-light text-accent-gold text-[9px] px-1.5 py-0.5"
          >
            {isSaved ? 'Slot Out' : 'Slot in'}
          </button>
        </div>
      </div>
    </div>
  )
}
