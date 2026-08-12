import { Clock, Crown, Eye, Film, Info, Layers, Lock, ShieldAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import StatusBadge from '@/components/StatusBadge'
import VideoCard from '@/components/VideoCard'
import VideoPlayer from '@/components/player/VideoPlayer'
import CommentSection from '@/features/engagement/CommentSection'
import ReactionBar from '@/features/engagement/ReactionBar'
import { BookmarkButton, FollowButton } from '@/features/library/controls'
import { Badge, EmptyState, ErrorState, LoadingBlock } from '@/components/ui'
import { formatAbsolute, formatCount, formatDuration } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'
import { useRelatedVideos } from '@/features/engagement/api'
import AdOverlay from '@/features/monetization/AdOverlay'
import { useAdBreaks } from '@/hooks/useAdBreaks'
import { useViewTracking } from '@/hooks/useViewTracking'
import { usePlayback, useVideo } from '@/features/videos/api'

function RelatedRail({ videoId }) {
  const { t } = useTranslation()
  const { data, isLoading } = useRelatedVideos(videoId)

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="flex gap-2">
            <div className="sv-skeleton aspect-video w-40 shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="sv-skeleton h-3 w-full" />
              <div className="sv-skeleton h-3 w-2/3" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  const results = data?.results ?? []
  if (results.length === 0) return null

  return (
    <aside>
      <h2 className="mb-3 text-sm font-semibold">{t('watch.related')}</h2>
      <div className="space-y-4">
        {results.map((video) => (
          <VideoCard key={video.id} video={video} />
        ))}
      </div>
      {/* Said plainly rather than implied: this rail is tag/category overlap,
          not a personalised model. */}
      <p className="mt-4 flex items-start gap-2 text-xs text-ink-500">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        {t('watch.relatedNote')}
      </p>
    </aside>
  )
}

export default function WatchPage() {
  const { t, i18n } = useTranslation()
  const { videoId } = useParams()
  const language = i18n.language

  const videoQuery = useVideo(videoId)
  const playbackQuery = usePlayback(videoId)
  const { setPlaying, viewState } = useViewTracking(videoId, {
    enabled: videoQuery.data?.status === 'ready',
  })
  // Whether ads run at all is the server's decision — this only sequences what
  // it returned.
  const adBreaks = useAdBreaks(videoId, {
    enabled: videoQuery.data?.status === 'ready',
  })

  if (videoQuery.isLoading) return <LoadingBlock label={t('watch.loading')} />

  if (videoQuery.isError) {
    const status = videoQuery.error?.response?.status
    if (status === 404 || status === 403) {
      return (
        <div className="mx-auto max-w-xl py-14">
          <EmptyState
            icon={Lock}
            title={t('watch.unavailable')}
            description={t('watch.unavailableHint')}
          />
        </div>
      )
    }
    return <ErrorState error={videoQuery.error} onRetry={videoQuery.refetch} />
  }

  const video = videoQuery.data
  const viewCount = viewState?.view_count ?? video.view_count

  return (
    <div className="mx-auto grid max-w-[1500px] gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        {/* ---------------------------------------------------------- player */}
        {video.status === 'ready' ? (
          playbackQuery.isLoading ? (
            <div className="grid aspect-video w-full place-items-center rounded-card bg-ink-950">
              <LoadingBlock label={t('watch.loading')} />
            </div>
          ) : playbackQuery.isError ? (
            <div className="grid aspect-video w-full place-items-center rounded-card bg-ink-950 p-6">
              <ErrorState error={playbackQuery.error} onRetry={playbackQuery.refetch} />
            </div>
          ) : (
            <VideoPlayer
              source={playbackQuery.data}
              title={video.title}
              onPlayingChange={setPlaying}
              onProgress={adBreaks.onProgress}
              adPlaying={Boolean(adBreaks.currentAd)}
              adOverlay={
                adBreaks.currentAd ? (
                  <AdOverlay ad={adBreaks.currentAd} onFinish={adBreaks.finishAd} />
                ) : null
              }
            />
          )
        ) : (
          <div className="grid aspect-video w-full place-items-center rounded-card border border-ink-800 bg-ink-950 text-center">
            <div className="space-y-3 px-6">
              {video.status === 'failed' ? (
                <ShieldAlert className="mx-auto size-10 text-red-400" aria-hidden />
              ) : (
                <Film className="mx-auto size-10 text-amber-400" aria-hidden />
              )}
              <p className="text-sm text-ink-300">
                {video.status === 'failed' ? t('watch.failed') : t('watch.processing')}
              </p>
              <StatusBadge status={video.status} />
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------- header */}
        <div className="mt-5">
          <h1 className="text-xl font-bold sm:text-2xl">{video.title}</h1>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-400">
            <span className="inline-flex items-center gap-1.5">
              <Eye className="size-4" aria-hidden />
              {formatCount(viewCount, language)} {t('common.views')}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-4" aria-hidden />
              {formatDuration(video.duration_seconds)}
            </span>
            {video.published_at && (
              <span>
                {t('watch.publishedOn', {
                  date: formatAbsolute(video.published_at, language),
                })}
              </span>
            )}
            {video.category && (
              <Link to={`/browse?category=${video.category.slug}`}>
                <Badge tone="brand">{categoryLabel(video.category, t)}</Badge>
              </Link>
            )}
            {adBreaks.isAdFree && (
              <Badge tone="success">
                <Crown className="size-3" aria-hidden />
                {t('ads.adFree')}
              </Badge>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-850 p-3">
            {video.uploader && (
              <Link
                to={`/c/${video.uploader.username}`}
                className="flex min-w-0 items-center gap-3 transition hover:opacity-80"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-bold text-white">
                  {(video.uploader.display_name || video.uploader.username)
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">
                    {video.uploader.display_name}
                  </span>
                  <span className="block truncate text-xs text-ink-400">
                    @{video.uploader.username}
                  </span>
                </span>
              </Link>
            )}

            {video.uploader && (
              <FollowButton
                username={video.uploader.username}
                isFollowing={video.is_following_uploader}
                followerCount={video.uploader_follower_count}
                isSelf={video.is_owner}
                size="sm"
              />
            )}

            {video.status === 'ready' && (
              <div className="flex flex-wrap items-center gap-2">
                <ReactionBar video={video} />
                <BookmarkButton videoId={video.id}
                                isBookmarked={video.is_bookmarked} />
              </div>
            )}
          </div>
        </div>

        {/* ----------------------------------------------------- description */}
        <section className="mt-4 rounded-card border border-ink-800 bg-ink-850 p-4">
          <h2 className="mb-2 text-sm font-semibold">{t('watch.description')}</h2>
          <p className="whitespace-pre-line text-sm leading-relaxed text-ink-300">
            {video.description || t('watch.noDescription')}
          </p>

          {video.tags?.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {video.tags.map((tag) => (
                <Link key={tag.slug} to={`/search?q=${encodeURIComponent(tag.name)}`}>
                  <Badge>#{tag.name}</Badge>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* --------------------------------------------------- tech details */}
        {video.renditions?.length > 0 && (
          <section className="mt-4 rounded-card border border-ink-800 bg-ink-850 p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Layers className="size-4 text-brand-400" aria-hidden />
              {t('watch.renditions')}
            </h2>
            <div className="flex flex-wrap gap-2">
              {video.renditions.map((rendition) => (
                <Badge key={rendition.label} tone="neutral">
                  {rendition.label} · {rendition.width}x{rendition.height} ·{' '}
                  {rendition.video_bitrate_kbps} kbps
                </Badge>
              ))}
            </div>
            <p className="mt-3 text-xs text-ink-400">
              {t('watch.sourceResolution')}: {video.source_resolution || '—'}
              {playbackQuery.data && (
                <>
                  {' · '}
                  {playbackQuery.data.delivery === 'public'
                    ? t('watch.deliveryPublic')
                    : t('watch.deliverySigned')}
                </>
              )}
            </p>
          </section>
        )}

        {/* --------------------------------------------------------- comments */}
        {video.status === 'ready' && (
          <CommentSection videoId={video.id} commentCount={video.comment_count} />
        )}
      </div>

      {/* ------------------------------------------------------------ sidebar */}
      <div className="min-w-0">
        <RelatedRail videoId={videoId} />
      </div>
    </div>
  )
}
