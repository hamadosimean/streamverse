import { Eye, Film, Lock, Link2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatCount, formatDuration, formatRelative } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'

/**
 * One video in a grid.
 *
 * The poster is `loading="lazy"` and the container reserves the 16:9 box before
 * the image loads, so a feed of 24 cards neither fetches 24 images up front nor
 * reflows as they arrive.
 */
export default function VideoCard({ video, className }) {
  const { t, i18n } = useTranslation()
  const language = i18n.language

  return (
    <article className={cn('group', className)}>
      <Link
        to={`/watch/${video.id}`}
        className="block overflow-hidden rounded-card bg-ink-850 focus-visible:outline-2 focus-visible:outline-brand-400"
      >
        <div className="relative aspect-video w-full overflow-hidden bg-ink-800">
          {video.poster_url ? (
            <img
              src={video.poster_url}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-full object-cover transition duration-300 group-hover:scale-105"
            />
          ) : (
            <div className="grid size-full place-items-center text-ink-600">
              <Film className="size-8" aria-hidden />
            </div>
          )}

          {video.duration_seconds > 0 && (
            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white">
              {formatDuration(video.duration_seconds)}
            </span>
          )}

          {video.visibility === 'unlisted' && (
            <span
              className="absolute left-2 top-2 rounded bg-black/80 p-1 text-amber-300"
              title={t('video.visibility.unlisted')}
            >
              <Link2 className="size-3.5" aria-hidden />
            </span>
          )}
          {video.visibility === 'private' && (
            <span
              className="absolute left-2 top-2 rounded bg-black/80 p-1 text-ink-300"
              title={t('video.visibility.private')}
            >
              <Lock className="size-3.5" aria-hidden />
            </span>
          )}
        </div>
      </Link>

      <div className="mt-2.5 space-y-1">
        <Link to={`/watch/${video.id}`}>
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-ink-100 transition group-hover:text-brand-300">
            {video.title}
          </h3>
        </Link>

        {video.uploader && (
          <p className="truncate text-xs text-ink-400">{video.uploader.display_name}</p>
        )}

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-400">
          <span className="inline-flex items-center gap-1">
            <Eye className="size-3.5" aria-hidden />
            {formatCount(video.view_count, language)}
          </span>
          {video.published_at && (
            <>
              <span aria-hidden>•</span>
              <span>{formatRelative(video.published_at, language)}</span>
            </>
          )}
          {video.category && (
            <Badge tone="brand" className="ml-auto">
              {categoryLabel(video.category, t)}
            </Badge>
          )}
        </div>
      </div>
    </article>
  )
}

export function VideoGrid({ videos, className }) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
        className,
      )}
    >
      {videos.map((video) => (
        <VideoCard key={video.id} video={video} />
      ))}
    </div>
  )
}
