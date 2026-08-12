import { Eye, Radio, RadioTower } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Badge, Button, EmptyState, ErrorState, SkeletonGrid } from '@/components/ui'
import { formatCount, formatRelative } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'
import { useLiveChannels } from '@/features/live/api'
import { useAuthStore } from '@/stores/useAuthStore'

function LiveCard({ channel }) {
  const { t, i18n } = useTranslation()

  return (
    <article className="group">
      <Link
        to={`/live/${channel.slug}`}
        className="block overflow-hidden rounded-card bg-ink-850 focus-visible:outline-2 focus-visible:outline-brand-400"
      >
        <div className="relative grid aspect-video w-full place-items-center bg-gradient-to-br from-red-900/40 via-ink-850 to-brand-900/30">
          <RadioTower className="size-10 text-red-400/70" aria-hidden />
          <span className="absolute left-2 top-2 inline-flex items-center gap-1.5 rounded bg-red-600 px-2 py-0.5 text-[11px] font-bold uppercase text-white">
            <span className="size-1.5 animate-pulse rounded-full bg-white" />
            {t('live.badge')}
          </span>
          <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded bg-black/80 px-1.5 py-0.5 text-[11px] text-white">
            <Eye className="size-3" aria-hidden />
            {formatCount(channel.current_viewer_count, i18n.language)}
          </span>
        </div>
      </Link>

      <div className="mt-2.5 space-y-1">
        <Link to={`/live/${channel.slug}`}>
          <h3 className="line-clamp-2 text-sm font-semibold transition group-hover:text-brand-300">
            {channel.title || channel.slug}
          </h3>
        </Link>
        <p className="truncate text-xs text-ink-400">{channel.user?.display_name}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-400">
          {channel.started_at && (
            <span>{t('live.startedAt', {
              time: formatRelative(channel.started_at, i18n.language),
            })}</span>
          )}
          {channel.category && (
            <Badge tone="brand">{categoryLabel(channel.category, t)}</Badge>
          )}
        </div>
      </div>
    </article>
  )
}

export default function LivePage() {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)
  const { data, isLoading, isError, error, refetch } = useLiveChannels()

  const channels = data ?? []

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Radio className="size-6 text-red-400" aria-hidden />
            {t('live.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-400">{t('live.subtitle')}</p>
        </div>
        {user && (
          <Link to="/studio/live">
            <Button variant="secondary">
              <RadioTower className="size-4" />
              {t('live.goLiveSetup')}
            </Button>
          </Link>
        )}
      </header>

      {isLoading && <SkeletonGrid count={4} />}
      {isError && <ErrorState error={error} onRetry={refetch} />}

      {data && channels.length === 0 && (
        <EmptyState
          icon={RadioTower}
          title={t('live.noneLive')}
          description={t('live.noneLiveHint')}
          action={
            user && (
              <Link to="/studio/live">
                <Button size="sm">{t('live.goLiveSetup')}</Button>
              </Link>
            )
          }
        />
      )}

      {channels.length > 0 && (
        <div className="grid grid-cols-1 gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {channels.map((channel) => (
            <LiveCard key={channel.slug} channel={channel} />
          ))}
        </div>
      )}
    </div>
  )
}
