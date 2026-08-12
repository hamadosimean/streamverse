import {
  BarChart3,
  Coins,
  Eye,
  Info,
  MousePointerClick,
  Pause,
  Play,
  Plus,
  Trash2,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import CampaignFormModal from '@/features/admin/CampaignFormModal'
import { Badge, Button, EmptyState, LoadingBlock, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import { formatAbsolute, formatCount } from '@/lib/format'
import {
  useAdCampaigns,
  useAdStats,
  useDeleteCampaign,
  useSaveCampaign,
} from '@/features/monetization/api'

const STATUS_TONES = {
  draft: 'neutral',
  active: 'success',
  paused: 'warning',
  ended: 'neutral',
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

/**
 * Ad-campaign management.
 *
 * A dedicated view rather than Django admin CRUD, because this is a decision
 * workflow: an operator scans delivery against caps and pauses or resumes
 * campaigns. Those actions are one click here; in a generic model form they are
 * buried in a field list.
 */
export default function AdCampaignsPage() {
  const { t, i18n } = useTranslation()
  const [statusFilter, setStatusFilter] = useState('')
  const [editing, setEditing] = useState(null)
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState(null)

  const campaignsQuery = useAdCampaigns(statusFilter || undefined)
  const statsQuery = useAdStats()
  const save = useSaveCampaign()
  const remove = useDeleteCampaign()

  const campaigns = campaignsQuery.data?.results ?? []
  const stats = statsQuery.data

  const toggleStatus = async (campaign) => {
    const next = campaign.status === 'active' ? 'paused' : 'active'
    try {
      await save.mutateAsync({ id: campaign.id, payload: { status: next } })
      toast.success(t(`ads.admin.now.${next}`))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const doDelete = async () => {
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('ads.admin.deleted'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  if (campaignsQuery.isLoading) return <LoadingBlock />

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{t('ads.admin.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('ads.admin.subtitle')}</p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="size-4" />
          {t('ads.admin.newCampaign')}
        </Button>
      </header>

      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile icon={BarChart3} label={t('ads.admin.campaigns')} value={stats.campaigns} />
          <StatTile
            icon={Eye}
            label={t('ads.admin.impressions')}
            value={formatCount(stats.impressions, i18n.language)}
          />
          <StatTile
            icon={MousePointerClick}
            label={t('ads.admin.clicks')}
            value={formatCount(stats.clicks, i18n.language)}
          />
          <StatTile
            icon={Users}
            label={t('ads.admin.subscribers')}
            value={formatCount(stats.active_subscriptions, i18n.language)}
          />
          <StatTile
            icon={Coins}
            label={t('ads.admin.revenue')}
            value={`${formatCount(stats.revenue_fcfa, i18n.language)} F`}
          />
        </div>
      )}

      <p className="mb-6 flex items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
        <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
        {t('ads.admin.scopeNote')}
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {['', 'active', 'paused', 'draft', 'ended'].map((value) => (
          <button
            key={value || 'all'}
            type="button"
            onClick={() => setStatusFilter(value)}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition',
              statusFilter === value
                ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                : 'border-ink-700 text-ink-300 hover:border-ink-600',
            )}
          >
            {value ? t(`ads.admin.status.${value}`) : t('common.all')}
          </button>
        ))}
      </div>

      {campaigns.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title={t('ads.admin.noCampaigns')}
          description={t('ads.admin.noCampaignsHint')}
          action={<Button size="sm" onClick={() => setCreating(true)}>
            {t('ads.admin.newCampaign')}
          </Button>}
        />
      ) : (
        <div className="space-y-3">
          {campaigns.map((campaign) => {
            const capPercent = campaign.impression_cap
              ? Math.min(100, Math.round(
                  (campaign.impression_count / campaign.impression_cap) * 100))
              : null
            return (
              <div
                key={campaign.id}
                className="flex flex-col gap-3 rounded-card border border-ink-800 bg-ink-850 p-4 sm:flex-row sm:items-center"
              >
                {campaign.creative_url && (
                  <div className="aspect-video w-full shrink-0 overflow-hidden rounded-lg bg-ink-800 sm:w-32">
                    {campaign.creative_is_video ? (
                      // eslint-disable-next-line jsx-a11y/media-has-caption
                      <video src={campaign.creative_url} className="size-full object-cover" muted />
                    ) : (
                      <img src={campaign.creative_url} alt="" className="size-full object-cover" />
                    )}
                  </div>
                )}

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-semibold">{campaign.title}</p>
                    <Badge tone={STATUS_TONES[campaign.status]}>
                      {t(`ads.admin.status.${campaign.status}`)}
                    </Badge>
                    <Badge>{t(`ads.placement.${campaign.placement}`)}</Badge>
                  </div>

                  <p className="mt-0.5 text-xs text-ink-400">
                    {campaign.advertiser_name} ·{' '}
                    {formatAbsolute(campaign.start_date, i18n.language)} →{' '}
                    {formatAbsolute(campaign.end_date, i18n.language)}
                  </p>

                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
                    <span>
                      {formatCount(campaign.impression_count, i18n.language)}{' '}
                      {t('ads.admin.impressions').toLowerCase()}
                      {campaign.impression_cap > 0 &&
                        ` / ${formatCount(campaign.impression_cap, i18n.language)}`}
                    </span>
                    <span>
                      {Math.round(campaign.completion_rate * 100)}%{' '}
                      {t('ads.admin.completionRate')}
                    </span>
                    <span>
                      {formatCount(campaign.click_count, i18n.language)}{' '}
                      {t('ads.admin.clicks').toLowerCase()}
                    </span>
                  </div>

                  {capPercent !== null && (
                    <div className="mt-2 h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-ink-700">
                      <div
                        className={cn('h-full rounded-full',
                                      capPercent >= 100 ? 'bg-red-500' : 'bg-brand-500')}
                        style={{ width: `${capPercent}%` }}
                      />
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 gap-1.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => toggleStatus(campaign)}
                    aria-label={campaign.status === 'active'
                      ? t('ads.admin.pause') : t('ads.admin.activate')}
                    title={campaign.status === 'active'
                      ? t('ads.admin.pause') : t('ads.admin.activate')}
                  >
                    {campaign.status === 'active'
                      ? <Pause className="size-4" />
                      : <Play className="size-4" />}
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setEditing(campaign)}>
                    {t('common.edit')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setPendingDelete(campaign)}
                    aria-label={t('common.delete')}
                  >
                    <Trash2 className="size-4 text-red-400" />
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <CampaignFormModal
        open={creating || Boolean(editing)}
        campaign={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      />

      <Modal
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        title={t('common.delete')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPendingDelete(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={doDelete}>
              {t('common.delete')}
            </Button>
          </>
        }
      >
        {pendingDelete && t('ads.admin.deleteConfirm', { title: pendingDelete.title })}
      </Modal>
    </div>
  )
}
