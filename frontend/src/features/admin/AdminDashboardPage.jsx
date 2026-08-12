import {
  Coins,
  Eye,
  Film,
  Flag,
  HardDrive,
  LayoutDashboard,
  Radio,
  Users,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Badge, ErrorState, LoadingBlock } from '@/components/ui'
import { formatBytes, formatCount, formatDuration } from '@/lib/format'
import { useAdminDashboard } from '@/features/moderation/api'

const CHART_TOOLTIP = {
  background: '#12121c',
  border: '1px solid #262637',
  borderRadius: 8,
  fontSize: 12,
}

const STATUS_COLORS = {
  ready: '#10b981',
  processing: '#f59e0b',
  failed: '#ef4444',
  taken_down: '#6b7280',
}

function Tile({ icon: Icon, label, value, sub, to }) {
  const body = (
    <div className="h-full rounded-card border border-ink-800 bg-ink-850 p-4 transition hover:border-ink-700">
      <div className="flex items-center gap-2 text-xs text-ink-400">
        <Icon className="size-4 text-brand-400" aria-hidden />
        {label}
      </div>
      <p className="mt-2 text-2xl font-bold tabular-nums">{value}</p>
      {sub && <p className="mt-1 text-xs text-ink-500">{sub}</p>}
    </div>
  )
  return to ? <Link to={to}>{body}</Link> : body
}

export default function AdminDashboardPage() {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const { data, isLoading, isError, error, refetch } = useAdminDashboard()

  if (isLoading) return <LoadingBlock />
  if (isError) return <ErrorState error={error} onRetry={refetch} />

  const statusData = Object.entries(data.videos)
    .filter(([key, value]) => STATUS_COLORS[key] && value > 0)
    .map(([key, value]) => ({
      name: t(`video.status.${key}`),
      value,
      color: STATUS_COLORS[key],
    }))

  // The two series share an x-axis of dates but come from different queries;
  // merged here so the chart shows them against each other.
  const activity = (() => {
    const byDate = new Map()
    for (const row of data.uploads_by_day ?? []) {
      byDate.set(row.date, { date: row.date, uploads: row.count, signups: 0 })
    }
    for (const row of data.signups_by_day ?? []) {
      const existing = byDate.get(row.date)
      if (existing) existing.signups = row.count
      else byDate.set(row.date, { date: row.date, uploads: 0, signups: row.count })
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date))
  })()

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <LayoutDashboard className="size-6 text-brand-400" aria-hidden />
          {t('admin.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-400">{t('admin.subtitle')}</p>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          icon={Users}
          label={t('admin.users')}
          value={formatCount(data.users.total, language)}
          sub={t('admin.newLast30', { count: data.users.new_30d })}
        />
        <Tile
          icon={Film}
          label={t('admin.videos')}
          value={formatCount(data.videos.total, language)}
          sub={t('admin.readyCount', { count: data.videos.ready })}
        />
        <Tile
          icon={Eye}
          label={t('admin.totalViews')}
          value={formatCount(data.videos.total_views, language)}
          sub={formatDuration(data.videos.total_duration_seconds)}
        />
        <Tile
          icon={Coins}
          label={t('admin.revenue30d')}
          value={`${formatCount(data.monetization.revenue_30d, language)} F`}
          sub={t('admin.activeSubs', {
            count: data.monetization.active_subscriptions,
          })}
        />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          icon={Flag}
          label={t('admin.pendingReports')}
          value={data.engagement.pending_reports}
          sub={t('admin.openQueue')}
          to="/manage/moderation"
        />
        <Tile
          icon={Radio}
          label={t('admin.liveNow')}
          value={data.live.live_now}
          sub={t('admin.channelCount', { count: data.live.channels })}
          to="/live"
        />
        <Tile
          icon={HardDrive}
          label={t('admin.storage')}
          value={formatBytes(data.storage.renditions_bytes, language)}
          sub={t('admin.storageNote')}
        />
        <Tile
          icon={Users}
          label={t('admin.suspended')}
          value={data.users.suspended}
          sub={t('admin.moderatorCount', { count: data.users.moderators })}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-card border border-ink-800 bg-ink-850 p-4 lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold">{t('admin.activity')}</h2>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activity}>
              <defs>
                <linearGradient id="up" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="su" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22c55e" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#262637" vertical={false} />
              <XAxis dataKey="date" stroke="#8b8ba7" fontSize={11} tickLine={false}
                     axisLine={false} tickFormatter={(v) => v.slice(5)} />
              <YAxis stroke="#8b8ba7" fontSize={11} tickLine={false}
                     axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={CHART_TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="uploads" name={t('admin.uploads')}
                    stroke="#818cf8" strokeWidth={2} fill="url(#up)" />
              <Area type="monotone" dataKey="signups" name={t('admin.signups')}
                    stroke="#4ade80" strokeWidth={2} fill="url(#su)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-card border border-ink-800 bg-ink-850 p-4">
          <h2 className="mb-4 text-sm font-semibold">{t('studio.statusBreakdown')}</h2>
          {statusData.length === 0 ? (
            <p className="py-16 text-center text-xs text-ink-400">{t('common.none')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={statusData} dataKey="value" nameKey="name"
                     innerRadius={50} outerRadius={80} paddingAngle={3}>
                  {statusData.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} stroke="none" />
                  ))}
                </Pie>
                <Tooltip contentStyle={CHART_TOOLTIP} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        <Link to="/manage/moderation">
          <Badge tone="brand">{t('admin.goModeration')}</Badge>
        </Link>
        <Link to="/manage/ads">
          <Badge tone="brand">{t('admin.goAds')}</Badge>
        </Link>
        <a href="/admin/">
          <Badge>{t('admin.goDjango')}</Badge>
        </a>
        <a href="/api/docs/">
          <Badge>{t('admin.goApiDocs')}</Badge>
        </a>
      </div>
    </div>
  )
}
