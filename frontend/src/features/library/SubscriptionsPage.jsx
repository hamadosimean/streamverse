import { Info, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { VideoGrid } from '@/components/VideoCard'
import { Button, EmptyState, ErrorState, SkeletonGrid } from '@/components/ui'
import { useFollowing, useFollowingFeed } from '@/features/library/api'

/**
 * Videos from the channels you follow.
 *
 * Strictly chronological. The platform has no recommendation model and this feed
 * does not pretend to be one — it is "what the people you follow posted, newest
 * first", and the note at the bottom says so.
 */
export default function SubscriptionsPage() {
  const { t } = useTranslation()
  const feed = useFollowingFeed()
  const following = useFollowing()

  const videos = feed.data?.results ?? []
  const channels = following.data?.results ?? []

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{t('library.subscriptionsTitle')}</h1>
          <p className="mt-1 text-sm text-ink-400">
            {t('library.subscriptionsSubtitle')}
          </p>
        </div>
        <Link to="/library?tab=following">
          <Button variant="secondary" size="sm">
            <UserPlus className="size-4" />
            {t('library.manageFollowing', { count: channels.length })}
          </Button>
        </Link>
      </header>

      {channels.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          {channels.map((row) => (
            <Link
              key={row.channel.username}
              to={`/c/${row.channel.username}`}
              className="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-850 py-1.5 pl-1.5 pr-3 text-xs transition hover:border-ink-600"
            >
              <span className="grid size-6 place-items-center rounded-full bg-brand-600 text-[10px] font-bold text-white">
                {(row.channel.display_name || row.channel.username)
                  .slice(0, 2).toUpperCase()}
              </span>
              {row.channel.display_name}
            </Link>
          ))}
        </div>
      )}

      {feed.isLoading && <SkeletonGrid count={8} />}
      {feed.isError && <ErrorState error={feed.error} onRetry={feed.refetch} />}

      {feed.data && videos.length === 0 && (
        <EmptyState
          icon={UserPlus}
          title={
            channels.length === 0
              ? t('library.emptyFollowing')
              : t('library.emptyFeed')
          }
          description={
            channels.length === 0
              ? t('library.emptyFollowingHint')
              : t('library.emptyFeedHint')
          }
          action={
            <Link to="/browse">
              <Button size="sm">{t('nav.browse')}</Button>
            </Link>
          }
        />
      )}

      {videos.length > 0 && (
        <>
          <VideoGrid videos={videos} />
          <p className="mt-8 flex items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
            <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
            {t('library.feedNote')}
          </p>
        </>
      )}
    </div>
  )
}
