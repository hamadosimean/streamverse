import {
  Clock,
  Eye,
  Film,
  Heart,
  Info,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import StatusBadge, { VisibilityBadge } from '@/components/StatusBadge'
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Modal,
  ProgressBar,
} from '@/components/ui'
import { formatCount, formatDuration, formatRelative } from '@/lib/format'
import {
  useDeleteVideo,
  useRetryTranscode,
  useStudioStats,
  useStudioVideos,
} from '@/features/videos/api'

const STATUS_COLORS = {
  ready: '#10b981',
  processing: '#f59e0b',
  failed: '#ef4444',
  taken_down: '#6b7280',
}

function StatTile({ icon: Icon, label, value }) {
  return (
    <div className="rounded-card border border-ink-800 bg-ink-850 p-4">
      <div className="flex items-center gap-2 text-xs text-ink-400">
        <Icon className="size-4 text-brand-400" aria-hidden />
        {label}
      </div>
      <p className="mt-2 text-2xl font-bold tabular-nums">{value}</p>
    </div>
  )
}

function StudioCharts({ stats }) {
  const { t } = useTranslation()

  const statusData = Object.entries(stats.by_status)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => ({
      name: t(`video.status.${status}`),
      value: count,
      color: STATUS_COLORS[status],
    }))

  return (
    <div className="mb-8 grid gap-4 lg:grid-cols-3">
      <div className="rounded-card border border-ink-800 bg-ink-850 p-4 lg:col-span-3">
        <h3 className="mb-4 text-sm font-semibold">{t('studio.viewsOverTime')}</h3>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={stats.views_by_day ?? []}>
            <defs>
              <linearGradient id="viewsFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.6} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#262637" vertical={false} />
            <XAxis
              dataKey="date"
              stroke="#8b8ba7"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => value.slice(5)}
            />
            <YAxis
              stroke="#8b8ba7"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                background: '#12121c',
                border: '1px solid #262637',
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Area
              type="monotone"
              dataKey="count"
              stroke="#818cf8"
              strokeWidth={2}
              fill="url(#viewsFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-card border border-ink-800 bg-ink-850 p-4 lg:col-span-2">
        <h3 className="mb-4 text-sm font-semibold">{t('studio.uploadsOverTime')}</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={stats.uploads_by_day}>
            <CartesianGrid strokeDasharray="3 3" stroke="#262637" vertical={false} />
            <XAxis
              dataKey="date"
              stroke="#8b8ba7"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => value.slice(5)}
            />
            <YAxis
              stroke="#8b8ba7"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                background: '#12121c',
                border: '1px solid #262637',
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-card border border-ink-800 bg-ink-850 p-4">
        <h3 className="mb-4 text-sm font-semibold">{t('studio.statusBreakdown')}</h3>
        {statusData.length === 0 ? (
          <p className="py-12 text-center text-xs text-ink-400">{t('common.none')}</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={statusData}
                dataKey="value"
                nameKey="name"
                innerRadius={45}
                outerRadius={75}
                paddingAngle={3}
              >
                {statusData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} stroke="none" />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: '#12121c',
                  border: '1px solid #262637',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

function VideoRow({ video, onDelete, onRetry, retrying }) {
  const { t, i18n } = useTranslation()
  const language = i18n.language

  return (
    <div className="flex flex-col gap-3 rounded-card border border-ink-800 bg-ink-850 p-3 sm:flex-row sm:items-center">
      <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-lg bg-ink-800 sm:w-44">
        {video.poster_url ? (
          <img src={video.poster_url} alt="" loading="lazy" className="size-full object-cover" />
        ) : (
          <div className="grid size-full place-items-center text-ink-600">
            <Film className="size-6" aria-hidden />
          </div>
        )}
        {video.duration_seconds > 0 && (
          <span className="absolute bottom-1 right-1 rounded bg-black/80 px-1 text-[10px] tabular-nums text-white">
            {formatDuration(video.duration_seconds)}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{video.title}</p>

        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <StatusBadge status={video.status} />
          <VisibilityBadge visibility={video.visibility} />
          <span className="text-xs text-ink-400">
            {formatRelative(video.uploaded_at, language)}
          </span>
        </div>

        {video.status === 'processing' && (
          <div className="mt-2">
            <div className="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>{t(`video.stage.${video.processing_stage}`)}</span>
              <span className="tabular-nums">{video.processing_progress}%</span>
            </div>
            <ProgressBar value={video.processing_progress} />
          </div>
        )}

        {video.status === 'failed' && video.failure_reason && (
          <p className="mt-2 line-clamp-2 rounded border border-red-500/30 bg-red-500/5 p-2 text-[11px] text-red-300">
            {video.failure_reason}
          </p>
        )}

        {video.status === 'ready' && (
          <div className="mt-1.5 flex gap-3 text-xs text-ink-400">
            <span className="inline-flex items-center gap-1">
              <Eye className="size-3.5" aria-hidden />
              {formatCount(video.view_count, language)}
            </span>
            <span className="inline-flex items-center gap-1">
              <Heart className="size-3.5" aria-hidden />
              {formatCount(video.like_count, language)}
            </span>
            <span>{video.renditions?.length ?? 0} × HLS</span>
          </div>
        )}
      </div>

      <div className="flex shrink-0 gap-1.5">
        {video.status === 'ready' && (
          <Link to={`/watch/${video.id}`}>
            <Button variant="ghost" size="icon" aria-label={t('player.play')}>
              <Play className="size-4" />
            </Button>
          </Link>
        )}
        {video.status === 'failed' && (
          <Button
            variant="ghost"
            size="icon"
            loading={retrying}
            onClick={() => onRetry(video.id)}
            aria-label={t('common.retry')}
          >
            <RefreshCw className="size-4" />
          </Button>
        )}
        <Link to={`/studio/videos/${video.id}`}>
          <Button variant="ghost" size="icon" aria-label={t('common.edit')}>
            <Pencil className="size-4" />
          </Button>
        </Link>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onDelete(video)}
          aria-label={t('common.delete')}
        >
          <Trash2 className="size-4 text-red-400" />
        </Button>
      </div>
    </div>
  )
}

export default function StudioPage() {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const [pendingDelete, setPendingDelete] = useState(null)

  const videosQuery = useStudioVideos()
  const statsQuery = useStudioStats()
  const deleteVideo = useDeleteVideo()
  const retryTranscode = useRetryTranscode()

  const handleDelete = async () => {
    try {
      await deleteVideo.mutateAsync(pendingDelete.id)
      toast.success(t('studio.deleted'))
    } catch {
      toast.error(t('common.error'))
    } finally {
      setPendingDelete(null)
    }
  }

  const handleRetry = async (videoId) => {
    try {
      await retryTranscode.mutateAsync(videoId)
      toast.success(t('studio.retryQueued'))
    } catch {
      toast.error(t('studio.retryOnlyFailed'))
    }
  }

  if (videosQuery.isLoading || statsQuery.isLoading) return <LoadingBlock />
  if (videosQuery.isError) {
    return <ErrorState error={videosQuery.error} onRetry={videosQuery.refetch} />
  }

  const videos = videosQuery.data?.results ?? []
  const stats = statsQuery.data

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{t('studio.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('studio.subtitle')}</p>
        </div>
        <Link to="/upload">
          <Button>
            <Upload className="size-4" />
            {t('nav.upload')}
          </Button>
        </Link>
      </header>

      {stats && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile icon={Film} label={t('studio.totalVideos')} value={stats.totals.videos} />
            <StatTile
              icon={Eye}
              label={t('studio.totalViews')}
              value={formatCount(stats.totals.views, language)}
            />
            <StatTile
              icon={Heart}
              label={t('studio.totalLikes')}
              value={formatCount(stats.totals.likes, language)}
            />
            <StatTile
              icon={Clock}
              label={t('studio.totalDuration')}
              value={formatDuration(stats.totals.duration_seconds)}
            />
          </div>

          <p className="mb-6 flex items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
            <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
            {stats.engagement_available
              ? t('studio.engagementLive')
              : t('studio.engagementNotice')}
          </p>

          <StudioCharts stats={stats} />
        </>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('studio.myVideos')}</h2>

        {videos.length === 0 ? (
          <EmptyState
            icon={Film}
            title={t('studio.empty')}
            description={t('studio.emptyHint')}
            action={
              <Link to="/upload">
                <Button size="sm">{t('studio.uploadFirst')}</Button>
              </Link>
            }
          />
        ) : (
          <div className="space-y-3">
            {videos.map((video) => (
              <VideoRow
                key={video.id}
                video={video}
                onDelete={setPendingDelete}
                onRetry={handleRetry}
                retrying={retryTranscode.isPending}
              />
            ))}
          </div>
        )}
      </section>

      <Modal
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        title={t('common.delete')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPendingDelete(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" loading={deleteVideo.isPending} onClick={handleDelete}>
              {t('common.delete')}
            </Button>
          </>
        }
      >
        {pendingDelete && t('studio.deleteConfirm', { title: pendingDelete.title })}
      </Modal>
    </div>
  )
}
