import { Clock, Eye, Film, Info, ThumbsUp, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { VideoGrid } from '@/components/VideoCard'
import { EmptyState, ErrorState, LoadingBlock, SkeletonGrid } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute, formatCount, formatDuration } from '@/lib/format'
import { FollowButton } from '@/features/library/controls'
import { useChannel, useChannelVideos } from '@/features/engagement/api'
import { useDocumentMeta } from '@/hooks/useDocumentMeta'

const SORTS = [
  { value: 'recent', labelKey: 'browse.sortRecent' },
  { value: 'popular', labelKey: 'browse.sortTrending' },
  { value: 'oldest', labelKey: 'browse.sortOldest' },
]

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-300">
      <Icon className="size-4 text-brand-400" aria-hidden />
      <span className="font-semibold text-ink-100">{value}</span>
      <span className="text-ink-400">{label}</span>
    </div>
  )
}

export default function ChannelPage() {
  const { t, i18n } = useTranslation()
  const { username } = useParams()
  const [sort, setSort] = useState('recent')

  const channelQuery = useChannel(username)
  const videosQuery = useChannelVideos(username, sort)

  const metaChannel = channelQuery.data
  useDocumentMeta({
    title: metaChannel?.display_name || metaChannel?.username || username,
    description: metaChannel?.bio,
    type: 'profile',
    canonical: `${window.location.origin}/c/${username}`,
    jsonLd: metaChannel && {
      '@context': 'https://schema.org',
      '@type': 'ProfilePage',
      url: `${window.location.origin}/c/${metaChannel.username}`,
      mainEntity: {
        '@type': 'Person',
        name: metaChannel.display_name || metaChannel.username,
        alternateName: metaChannel.username,
        description: metaChannel.bio || undefined,
      },
    },
  })

  if (channelQuery.isLoading) return <LoadingBlock />
  if (channelQuery.isError) {
    const status = channelQuery.error?.response?.status
    if (status === 404) {
      return (
        <div className="mx-auto max-w-xl py-14">
          <EmptyState
            icon={Film}
            title={t('channel.notFound')}
            description={t('channel.notFoundHint')}
          />
        </div>
      )
    }
    return <ErrorState error={channelQuery.error} onRetry={channelQuery.refetch} />
  }

  const channel = channelQuery.data
  const stats = channel.stats ?? {}
  const videos = videosQuery.data?.results ?? []

  return (
    <div className="mx-auto max-w-[1400px]">
      <header className="mb-8 overflow-hidden rounded-card border border-ink-800">
        <div className="h-24 bg-gradient-to-r from-brand-700/40 via-ink-850 to-accent-500/25 sm:h-32" />

        <div className="flex flex-col gap-4 bg-ink-850 px-5 pb-5 sm:flex-row sm:items-end">
          <span
            className="-mt-10 grid size-20 shrink-0 place-items-center rounded-full border-4 border-ink-850 bg-brand-600 text-xl font-bold text-white sm:size-24 sm:text-2xl"
            aria-hidden
          >
            {(channel.display_name || channel.username).slice(0, 2).toUpperCase()}
          </span>

          <div className="min-w-0 flex-1 sm:pb-1">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h1 className="truncate text-xl font-bold sm:text-2xl">
                  {channel.display_name}
                </h1>
                <p className="text-sm text-ink-400">@{channel.username}</p>
              </div>
              <FollowButton
                username={channel.username}
                isFollowing={channel.is_following}
                followerCount={stats.follower_count}
                isSelf={channel.is_self}
              />
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
              <Stat icon={UserPlus} label={t('library.followers')}
                    value={formatCount(stats.follower_count ?? 0, i18n.language)} />
              <Stat icon={Film} label={t('channel.videos')} value={stats.video_count ?? 0} />
              <Stat
                icon={Eye}
                label={t('common.views')}
                value={formatCount(stats.total_views ?? 0, i18n.language)}
              />
              <Stat
                icon={ThumbsUp}
                label={t('common.likes')}
                value={formatCount(stats.total_likes ?? 0, i18n.language)}
              />
              <Stat
                icon={Clock}
                label={t('channel.totalDuration')}
                value={formatDuration(stats.total_duration_seconds ?? 0)}
              />
            </div>
          </div>
        </div>

        {channel.bio && (
          <p className="whitespace-pre-line border-t border-ink-800 bg-ink-850 px-5 py-4 text-sm text-ink-300">
            {channel.bio}
          </p>
        )}
      </header>

      {/* Following exists, but still no notifications: a follow changes only
          the follower's own feed and never messages the channel owner. */}
      <p className="mb-6 flex items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
        <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
        {t('channel.followNotice')}
        {channel.created_at &&
          ` · ${t('account.memberSince', {
            date: formatAbsolute(channel.created_at, i18n.language),
          })}`}
      </p>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">{t('channel.publicVideos')}</h2>
        <div className="ml-auto flex gap-1">
          {SORTS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setSort(option.value)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                sort === option.value
                  ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                  : 'border-ink-700 text-ink-300 hover:border-ink-600 hover:text-ink-100',
              )}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {videosQuery.isLoading && <SkeletonGrid count={8} />}
      {videosQuery.isError && (
        <ErrorState error={videosQuery.error} onRetry={videosQuery.refetch} />
      )}

      {videosQuery.data && videos.length === 0 && (
        <EmptyState
          icon={Film}
          title={t('channel.noVideos')}
          description={t('channel.noVideosHint')}
        />
      )}

      {videos.length > 0 && <VideoGrid videos={videos} />}
    </div>
  )
}
