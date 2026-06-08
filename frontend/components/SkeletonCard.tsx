export default function SkeletonCard({ variant }: { variant: 'digest' | 'feed' }) {
  if (variant === 'digest') {
    return (
      <div className="min-w-[160px] rounded-lg border border-border overflow-hidden flex-shrink-0">
        <div className="h-[60px] shimmer" />
        <div className="p-2 space-y-2">
          <div className="h-3 rounded shimmer" />
          <div className="h-2 w-2/3 rounded shimmer" />
          <div className="h-2 rounded shimmer" />
        </div>
      </div>
    )
  }
  return (
    <div className="flex h-[68px] rounded-lg border border-border overflow-hidden">
      <div className="w-20 shimmer flex-shrink-0" />
      <div className="flex-1 p-2 space-y-2">
        <div className="h-3 rounded shimmer" />
        <div className="h-2 w-1/2 rounded shimmer" />
      </div>
    </div>
  )
}
