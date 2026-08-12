import {
  Bookmark,
  History,
  PlayCircle,
  ThumbsUp,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link, useSearchParams } from 'react-router-dom'

import VideoCard, { VideoGrid } from '@/components/VideoCard'
import { BookmarkButton, FollowButton } from '@/features/library/controls'
import { Badge, Button, EmptyState, LoadingBlock, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatCount, formatDuration, formatRelative } from '@/lib/format'
import {
  useBookmarks,
  useClearHistory,
  useFollowing,
  useLibrarySummary,
  useLikedVideos,
  useRemoveFromHistory,
  useWatchHistory,
} from '@/features/library/api'

const TABS = [
  { key: 'history', icon: History },
  { key: 'bookmarks', icon: Bookmark },
  { key: 'liked', icon: ThumbsUp },
  { key: 'following', icon: UserPlus },
]

/** A history card with a resume bar and a remove control. */
function HistoryCard({ entry, onRemove }) {
  const { t, i18n } = useTranslation()
  const video = entry.video

  return (
    <article className="group relative">
      <Link
        to={`/watch/${video.id}`}
        className="block overflow-hidden rounded-card bg-ink-850"
      >
        <div className="relative aspect-video w-full overflow-hidden bg-ink-800">
          {video.poster_url && (
            <img src={video.poster_url} alt="" loading="lazy"
                 className="size-full object-cover transition group-hover:scale-105" />
          )}
          {video.duration_seconds > 0 && (
            <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-[11px] tabular-nums text-white">
              {formatDuration(video.duration_seconds)}
            </span>
          )}
          {/* The resume bar is the point of a history card — it tells you
              whether coming back means starting over. */}
          {entry.progress_percent > 0 && (
            <span className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
              <span className="block h-full bg-brand-500"
                    style={{ width: `${entry.progress_percent}%` }} />
            </span>
          )}
          {entry.completed && (
            <span className="absolute left-2 top-2 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white">
              {t('library.watched')}
            </span>
          )}
        </div>
      </Link>

      <button
        type="button"
        onClick={() => onRemove(video.id)}
        aria-label={t('library.removeFromHistory')}
        title={t('library.removeFromHistory')}
        className="absolute right-2 top-2 rounded-full bg-black/70 p-1.5 text-white opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
      >
        <X className="size-3.5" />
      </button>

      <div className="mt-2.5 space-y-1">
        <Link to={`/watch/${video.id}`}>
          <h3 className="line-clamp-2 text-sm font-semibold group-hover:text-brand-300">
            {video.title}
          </h3>
        </Link>
        <p className="truncate text-xs text-ink-400">{video.uploader?.display_name}</p>
        <p className="text-xs text-ink-500">
          {entry.is_resumable
            ? t('library.resumeAt', { time: formatDuration(entry.progress_seconds) })
            : formatRelative(entry.last_watched_at, i18n.language)}
        </p>
      </div>
    </article>
  )
}

export default function LibraryPage() {
  const { t, i18n } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = TABS.some((x) => x.key === searchParams.get('tab'))
    ? searchParams.get('tab')
    : 'history'
  const [confirmClear, setConfirmClear] = useState(false)

  const summary = useLibrarySummary()
  const historyQuery = useWatchHistory()
  const bookmarksQuery = useBookmarks()
  const likedQuery = useLikedVideos()
  const followingQuery = useFollowing()

  const clearHistory = useClearHistory()
  const removeEntry = useRemoveFromHistory()

  const counts = summary.data ?? {}
  const setTab = (key) => setSearchParams(key === 'history' ? {} : { tab: key })

  const active = {
    history: historyQuery,
    bookmarks: bookmarksQuery,
    liked: likedQuery,
    following: followingQuery,
  }[tab]

  const resumable = (historyQuery.data?.results ?? []).filter((e) => e.is_resumable)

  const doRemove = async (videoId) => {
    try {
      await removeEntry.mutateAsync(videoId)
    } catch {
      toast.error(t('common.error'))
    }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">{t('library.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('library.subtitle')}</p>
      </header>

      <div className="mb-6 flex flex-wrap items-center gap-2">
        {TABS.map(({ key, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              'inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-medium transition',
              tab === key
                ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                : 'border-ink-700 text-ink-300 hover:border-ink-600 hover:text-ink-100',
            )}
          >
            <Icon className="size-4" aria-hidden />
            {t(`library.tab.${key}`)}
            {counts[key] > 0 && (
              <span className="text-ink-500">{formatCount(counts[key], i18n.language)}</span>
            )}
          </button>
        ))}

        {tab === 'history' && (historyQuery.data?.count ?? 0) > 0 && (
          <Button variant="ghost" size="sm" className="ml-auto"
                  onClick={() => setConfirmClear(true)}>
            <Trash2 className="size-4" />
            {t('library.clearHistory')}
          </Button>
        )}
      </div>

      {active?.isLoading && <LoadingBlock />}

      {/* ------------------------------------------------------- history */}
      {tab === 'history' && historyQuery.data && (
        historyQuery.data.results.length === 0 ? (
          <EmptyState
            icon={History}
            title={t('library.emptyHistory')}
            description={t('library.emptyHistoryHint')}
            action={<Link to="/browse"><Button size="sm">{t('nav.browse')}</Button></Link>}
          />
        ) : (
          <>
            {resumable.length > 0 && (
              <section className="mb-8">
                <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
                  <PlayCircle className="size-5 text-brand-400" aria-hidden />
                  {t('library.continueWatching')}
                </h2>
                <div className="grid grid-cols-1 gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {resumable.slice(0, 4).map((entry) => (
                    <HistoryCard key={entry.video.id} entry={entry} onRemove={doRemove} />
                  ))}
                </div>
              </section>
            )}

            <h2 className="mb-4 text-lg font-semibold">{t('library.allHistory')}</h2>
            <div className="grid grid-cols-1 gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {historyQuery.data.results.map((entry) => (
                <HistoryCard key={entry.video.id} entry={entry} onRemove={doRemove} />
              ))}
            </div>
          </>
        )
      )}

      {/* ----------------------------------------------------- bookmarks */}
      {tab === 'bookmarks' && bookmarksQuery.data && (
        bookmarksQuery.data.results.length === 0 ? (
          <EmptyState
            icon={Bookmark}
            title={t('library.emptyBookmarks')}
            description={t('library.emptyBookmarksHint')}
          />
        ) : (
          <div className="grid grid-cols-1 gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {bookmarksQuery.data.results.map((row) => (
              <div key={row.video.id} className="relative">
                <VideoCard video={row.video} />
                <div className="mt-2">
                  <BookmarkButton videoId={row.video.id} isBookmarked showLabel={false} />
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {/* --------------------------------------------------------- liked */}
      {tab === 'liked' && likedQuery.data && (
        likedQuery.data.results.length === 0 ? (
          <EmptyState
            icon={ThumbsUp}
            title={t('library.emptyLiked')}
            description={t('library.emptyLikedHint')}
          />
        ) : (
          <VideoGrid videos={likedQuery.data.results} />
        )
      )}

      {/* ----------------------------------------------------- following */}
      {tab === 'following' && followingQuery.data && (
        followingQuery.data.results.length === 0 ? (
          <EmptyState
            icon={UserPlus}
            title={t('library.emptyFollowing')}
            description={t('library.emptyFollowingHint')}
            action={<Link to="/browse"><Button size="sm">{t('nav.browse')}</Button></Link>}
          />
        ) : (
          <div className="space-y-3">
            {followingQuery.data.results.map((row) => (
              <div key={row.channel.username}
                   className="flex flex-wrap items-center gap-4 rounded-card border border-ink-800 bg-ink-850 p-4">
                <Link to={`/c/${row.channel.username}`}
                      className="grid size-12 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-bold text-white">
                  {(row.channel.display_name || row.channel.username).slice(0, 2).toUpperCase()}
                </Link>
                <div className="min-w-0 flex-1">
                  <Link to={`/c/${row.channel.username}`}
                        className="block truncate text-sm font-semibold hover:text-brand-300">
                    {row.channel.display_name}
                  </Link>
                  <p className="truncate text-xs text-ink-400">
                    @{row.channel.username} · {t('channel.videos')}: {row.video_count}
                    {row.latest_video_at &&
                      ` · ${t('library.lastPublished', {
                        time: formatRelative(row.latest_video_at, i18n.language),
                      })}`}
                  </p>
                </div>
                <Badge>{t('library.followerCount', {
                  count: formatCount(row.follower_count ?? 0, i18n.language),
                })}</Badge>
                <FollowButton username={row.channel.username} isFollowing
                              followerCount={row.follower_count} size="sm" />
              </div>
            ))}
          </div>
        )
      )}

      <Modal
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        title={t('library.clearHistory')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmClear(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={clearHistory.isPending}
              onClick={async () => {
                await clearHistory.mutateAsync()
                setConfirmClear(false)
                toast.success(t('library.historyCleared'))
              }}
            >
              {t('library.clearHistory')}
            </Button>
          </>
        }
      >
        {t('library.clearHistoryConfirm')}
      </Modal>
    </div>
  )
}
