import { Eye, RadioTower, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import LiveChat from '@/features/live/LiveChat'
import LivePlayer from '@/features/live/LivePlayer'
import { Badge, EmptyState, ErrorState, LoadingBlock } from '@/components/ui'
import { formatCount, formatRelative } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'
import { useLiveChannel } from '@/features/live/api'
import { useLiveSocket } from '@/hooks/useLiveSocket'

export default function LiveWatchPage() {
  const { t, i18n } = useTranslation()
  const { slug } = useParams()

  const channelQuery = useLiveChannel(slug)
  const socket = useLiveSocket(slug)

  if (channelQuery.isLoading) return <LoadingBlock />

  if (channelQuery.isError) {
    const status = channelQuery.error?.response?.status
    if (status === 404) {
      return (
        <div className="mx-auto max-w-xl py-14">
          <EmptyState
            icon={RadioTower}
            title={t('live.notFound')}
            description={t('live.notFoundHint')}
          />
        </div>
      )
    }
    return <ErrorState error={channelQuery.error} onRetry={channelQuery.refetch} />
  }

  const channel = channelQuery.data
  // The socket is the fresher source once connected — it pushes status changes
  // the moment the broadcaster starts or stops.
  const status = socket.status ?? channel.status
  const isLive = status === 'live'
  const viewers = socket.connected ? socket.viewerCount : channel.current_viewer_count

  return (
    <div className="mx-auto grid max-w-[1500px] gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <LivePlayer
          src={channel.playback_url}
          isLive={isLive && Boolean(channel.playback_url)}
        />

        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            {isLive && (
              <Badge tone="danger">
                <span className="size-1.5 animate-pulse rounded-full bg-red-400" />
                {t('live.badge')}
              </Badge>
            )}
            <h1 className="text-xl font-bold sm:text-2xl">
              {channel.title || channel.slug}
            </h1>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-400">
            <span className="inline-flex items-center gap-1.5">
              <Users className="size-4" aria-hidden />
              {formatCount(viewers, i18n.language)} {t('live.viewers')}
            </span>
            {channel.peak_viewer_count > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <Eye className="size-4" aria-hidden />
                {t('live.peak', {
                  count: formatCount(channel.peak_viewer_count, i18n.language),
                })}
              </span>
            )}
            {isLive && channel.started_at && (
              <span>{t('live.startedAt', {
                time: formatRelative(channel.started_at, i18n.language),
              })}</span>
            )}
            {channel.category && (
              <Badge tone="brand">{categoryLabel(channel.category, t)}</Badge>
            )}
          </div>

          {channel.user && (
            <Link
              to={`/c/${channel.user.username}`}
              className="mt-4 flex items-center gap-3 rounded-card border border-ink-800 bg-ink-850 p-3 transition hover:border-ink-700"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-bold text-white">
                {(channel.user.display_name || channel.user.username)
                  .slice(0, 2)
                  .toUpperCase()}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">
                  {channel.user.display_name}
                </span>
                <span className="block truncate text-xs text-ink-400">
                  @{channel.user.username}
                </span>
              </span>
            </Link>
          )}

          {channel.description && (
            <p className="mt-4 whitespace-pre-line rounded-card border border-ink-800 bg-ink-850 p-4 text-sm text-ink-300">
              {channel.description}
            </p>
          )}
        </div>
      </div>

      <div className="min-w-0">
        <LiveChat slug={slug} socket={socket} chatEnabled={channel.chat_enabled} />
      </div>
    </div>
  )
}
