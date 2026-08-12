import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  Flag,
  Gavel,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import ReviewModal from '@/features/moderation/ReviewModal'
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatRelative } from '@/lib/format'
import { useModerationStats, useReportQueue } from '@/features/moderation/api'

const STATUS_TABS = ['pending', 'actioned', 'dismissed', 'all']

function StatTile({ icon: Icon, label, value, tone = 'brand' }) {
  const colors = {
    brand: 'text-brand-400',
    warning: 'text-amber-400',
    danger: 'text-red-400',
  }
  return (
    <div className="rounded-card border border-ink-800 bg-ink-850 p-4">
      <div className="flex items-center gap-2 text-xs text-ink-400">
        <Icon className={cn('size-4', colors[tone])} aria-hidden />
        {label}
      </div>
      <p className="mt-2 text-2xl font-bold tabular-nums">{value}</p>
    </div>
  )
}

/**
 * The moderation queue.
 *
 * A dedicated view rather than Django admin CRUD, because triaging a report is a
 * decision: you need the reported content, who wrote it, how many others
 * reported the same thing, and whether this author has been actioned before —
 * all on one screen, with four possible actions. A generic model form gives you
 * none of that.
 */
export default function ModerationQueuePage() {
  const { t, i18n } = useTranslation()
  const [statusTab, setStatusTab] = useState('pending')
  const [targetType, setTargetType] = useState('')
  const [reviewing, setReviewing] = useState(null)

  const params = {
    status: statusTab,
    ...(targetType && { target_type: targetType }),
  }
  const queueQuery = useReportQueue(params)
  const statsQuery = useModerationStats()

  const reports = queueQuery.data?.results ?? []
  const stats = statsQuery.data

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Gavel className="size-6 text-brand-400" aria-hidden />
          {t('moderation.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-400">{t('moderation.subtitle')}</p>
      </header>

      {stats && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile icon={Flag} label={t('moderation.pending')}
                      value={stats.pending} tone="warning" />
            <StatTile icon={CheckCircle2} label={t('moderation.actioned')}
                      value={stats.actioned} />
            <StatTile icon={XCircle} label={t('moderation.dismissed')}
                      value={stats.dismissed} />
            <StatTile icon={ShieldAlert} label={t('moderation.suspendedUsers')}
                      value={stats.suspended_users} tone="danger" />
          </div>

          {/* A growing oldest-item age is the first sign a queue is failing,
              long before the total count looks bad. */}
          {stats.oldest_pending_at && (
            <p className="mb-6 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
              <Clock className="size-3.5 shrink-0" aria-hidden />
              {t('moderation.oldestPending', {
                age: formatRelative(stats.oldest_pending_at, i18n.language),
              })}
            </p>
          )}
        </>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setStatusTab(value)}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition',
              statusTab === value
                ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                : 'border-ink-700 text-ink-300 hover:border-ink-600',
            )}
          >
            {value === 'all' ? t('common.all') : t(`moderation.status.${value}`)}
          </button>
        ))}

        <select
          value={targetType}
          onChange={(event) => setTargetType(event.target.value)}
          className="sv-input ml-auto w-auto py-1.5 text-xs"
          aria-label={t('moderation.targetType')}
        >
          <option value="">{t('moderation.allTypes')}</option>
          <option value="video">{t('engagement.reportTarget.video')}</option>
          <option value="comment">{t('engagement.reportTarget.comment')}</option>
        </select>
      </div>

      {queueQuery.isLoading && <LoadingBlock />}
      {queueQuery.isError && (
        <ErrorState error={queueQuery.error} onRetry={queueQuery.refetch} />
      )}

      {queueQuery.data && reports.length === 0 && (
        <EmptyState
          icon={CheckCircle2}
          title={t('moderation.queueEmpty')}
          description={t('moderation.queueEmptyHint')}
        />
      )}

      <div className="space-y-3">
        {reports.map((report) => {
          const target = report.target
          return (
            <div
              key={report.id}
              className="flex flex-col gap-3 rounded-card border border-ink-800 bg-ink-850 p-4 sm:flex-row"
            >
              {target?.poster_url && (
                <img
                  src={target.poster_url}
                  alt=""
                  className="aspect-video w-full shrink-0 rounded-lg object-cover sm:w-40"
                />
              )}

              <div className="min-w-0 flex-1">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <Badge tone="danger">{report.reason_label}</Badge>
                  <Badge>
                    {target
                      ? t(`engagement.reportTarget.${target.type}`)
                      : t('moderation.targetGone')}
                  </Badge>
                  {report.status !== 'pending' && (
                    <Badge tone={report.status === 'actioned' ? 'success' : 'neutral'}>
                      {t(`moderation.status.${report.status}`)}
                    </Badge>
                  )}
                  {target?.already_removed && (
                    <Badge tone="neutral">{t('moderation.alreadyRemoved')}</Badge>
                  )}
                  <span className="text-xs text-ink-500">
                    {formatRelative(report.created_at, i18n.language)}
                  </span>
                </div>

                <p className="truncate text-sm font-semibold">
                  {target?.title ?? t('moderation.targetGone')}
                </p>
                {target?.body && (
                  <p className="mt-1 line-clamp-2 text-xs text-ink-400">{target.body}</p>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
                  {target?.author && (
                    <span>
                      {t('moderation.author')}:{' '}
                      <Link to={`/c/${target.author.username}`}
                            className="text-brand-300 hover:underline">
                        {target.author.display_name}
                      </Link>
                    </span>
                  )}
                  <span>
                    {t('moderation.reportedBy')}: {report.reporter?.display_name}
                  </span>
                  {target?.url && (
                    <Link to={target.url}
                          className="inline-flex items-center gap-1 text-brand-300 hover:underline">
                      {t('moderation.viewContent')}
                      <ExternalLink className="size-3" aria-hidden />
                    </Link>
                  )}
                </div>

                {report.details && (
                  <p className="mt-2 rounded border border-ink-700 bg-ink-800 p-2 text-xs text-ink-300">
                    “{report.details}”
                  </p>
                )}

                {report.resolution_note && report.status !== 'pending' && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-ink-400">
                    <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                    {report.resolution_note}
                  </p>
                )}
              </div>

              <div className="flex shrink-0 items-start">
                {report.status === 'pending' ? (
                  <Button size="sm" onClick={() => setReviewing(report)}>
                    {t('moderation.review')}
                  </Button>
                ) : (
                  <span className="text-xs text-ink-500">
                    {report.reviewed_by?.display_name}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <ReviewModal
        report={reviewing}
        open={Boolean(reviewing)}
        onClose={() => setReviewing(null)}
      />
    </div>
  )
}
