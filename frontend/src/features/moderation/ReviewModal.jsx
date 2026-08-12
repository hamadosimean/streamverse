import { AlertTriangle, Ban, Check, Trash2, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import { Badge, Button, Field, LoadingBlock, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import { useReport, useResolveReport } from '@/features/moderation/api'

const ACTIONS = [
  { value: 'dismiss', icon: X, tone: 'neutral', needsReason: false },
  { value: 'remove', icon: Trash2, tone: 'danger', needsReason: true },
  { value: 'remove_and_warn', icon: TriangleAlert, tone: 'danger', needsReason: true },
  { value: 'remove_and_suspend', icon: Ban, tone: 'danger', needsReason: true },
]

/**
 * Review one report.
 *
 * The author's prior history is loaded and shown *before* the decision, not
 * after: "has this happened before" is the single most useful input to whether
 * a removal should also carry a warning or a suspension.
 */
export default function ReviewModal({ report, open, onClose }) {
  const { t, i18n } = useTranslation()
  const { data: detail, isLoading } = useReport(open ? report?.id : null)
  const resolve = useResolveReport()

  const [action, setAction] = useState('dismiss')
  const [reason, setReason] = useState('')
  const [suspendDays, setSuspendDays] = useState(7)

  useEffect(() => {
    if (open) {
      setAction('dismiss')
      setReason('')
      setSuspendDays(7)
    }
  }, [open, report?.id])

  const selected = ACTIONS.find((a) => a.value === action)
  const reasonTooShort = selected?.needsReason && reason.trim().length < 10

  const submit = async () => {
    try {
      await resolve.mutateAsync({
        reportId: report.id,
        action,
        reason: reason.trim(),
        ...(action === 'remove_and_suspend' && { suspend_days: suspendDays }),
      })
      toast.success(t('moderation.resolved'))
      onClose()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const history = detail?.author_history
  const target = detail?.target

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('moderation.reviewTitle')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant={action === 'dismiss' ? 'primary' : 'danger'}
            onClick={submit}
            loading={resolve.isPending}
            disabled={reasonTooShort}
          >
            {t(`moderation.action.${action}`)}
          </Button>
        </>
      }
    >
      {isLoading && <LoadingBlock />}

      {detail && (
        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          {/* ------------------------------------------------ the content */}
          <section className="rounded-lg border border-ink-700 bg-ink-800 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge tone="danger">{detail.reason_label}</Badge>
              {detail.duplicate_count > 0 && (
                <Badge tone="warning">
                  {t('moderation.alsoReported', { count: detail.duplicate_count })}
                </Badge>
              )}
            </div>
            <p className="text-sm font-semibold">
              {target?.title ?? t('moderation.targetGone')}
            </p>
            {target?.body && (
              <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-line text-xs text-ink-300">
                {target.body}
              </p>
            )}
            {detail.details && (
              <p className="mt-2 border-t border-ink-700 pt-2 text-xs text-ink-400">
                <span className="text-ink-500">{t('moderation.reporterSaid')}: </span>
                “{detail.details}”
              </p>
            )}
          </section>

          {/* --------------------------------------- the author's history */}
          {history && (
            <section
              className={cn(
                'rounded-lg border p-3 text-xs',
                history.is_repeat_offender
                  ? 'border-red-500/40 bg-red-500/10'
                  : 'border-ink-700 bg-ink-800',
              )}
            >
              <p className="mb-2 flex items-center gap-1.5 font-semibold">
                {history.is_repeat_offender && (
                  <AlertTriangle className="size-3.5 text-red-400" aria-hidden />
                )}
                {t('moderation.authorHistory', { days: history.window_days })}
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-ink-300">
                <span>
                  {t('moderation.videosRemoved')}: {history.videos_taken_down}
                </span>
                <span>
                  {t('moderation.commentsRemoved')}: {history.comments_removed}
                </span>
                <span>{t('moderation.warnings')}: {history.warnings}</span>
                <span>{t('moderation.suspensions')}: {history.suspensions}</span>
              </div>
              {history.currently_suspended && (
                <p className="mt-2 text-red-300">{t('moderation.alreadySuspended')}</p>
              )}
              {history.is_repeat_offender && (
                <p className="mt-2 font-medium text-red-300">
                  {t('moderation.repeatOffender')}
                </p>
              )}
            </section>
          )}

          {detail.recent_actions?.length > 0 && (
            <section className="rounded-lg border border-ink-700 bg-ink-800 p-3">
              <p className="mb-2 text-xs font-semibold">
                {t('moderation.recentActions')}
              </p>
              <ul className="space-y-1 text-xs text-ink-400">
                {detail.recent_actions.map((entry) => (
                  <li key={entry.id} className="truncate">
                    {formatRelative(entry.created_at, i18n.language)} —{' '}
                    {entry.action_label}: {entry.reason}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* --------------------------------------------------- decision */}
          <Field label={t('moderation.decision')} required>
            <div className="space-y-1.5">
              {ACTIONS.map((option) => {
                const Icon = option.icon
                return (
                  <label
                    key={option.value}
                    className={cn(
                      'flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 text-sm transition',
                      action === option.value
                        ? option.tone === 'danger'
                          ? 'border-red-500/60 bg-red-500/10'
                          : 'border-brand-500 bg-brand-500/10'
                        : 'border-ink-700 hover:border-ink-600',
                    )}
                  >
                    <input
                      type="radio"
                      name="moderation-action"
                      value={option.value}
                      checked={action === option.value}
                      onChange={(event) => setAction(event.target.value)}
                      className="accent-brand-500"
                    />
                    <Icon className="size-4" aria-hidden />
                    {t(`moderation.action.${option.value}`)}
                  </label>
                )
              })}
            </div>
          </Field>

          {action === 'remove_and_suspend' && (
            <Field label={t('moderation.suspendDays')}>
              <input
                type="number"
                min="1"
                max="3650"
                className="sv-input"
                value={suspendDays}
                onChange={(event) => setSuspendDays(Number(event.target.value))}
              />
            </Field>
          )}

          <Field
            label={t('moderation.reason')}
            required={selected?.needsReason}
            hint={
              selected?.needsReason
                ? t('moderation.reasonRequired')
                : t('moderation.reasonOptional')
            }
            error={
              reasonTooShort && reason.length > 0
                ? t('moderation.reasonTooShort')
                : undefined
            }
          >
            <textarea
              rows={3}
              maxLength={2000}
              className="sv-input resize-y"
              placeholder={t('moderation.reasonPlaceholder')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>

          <p className="flex items-start gap-2 rounded-lg border border-ink-700 bg-ink-800 p-2.5 text-xs text-ink-400">
            <Check className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
            {t('moderation.auditNote')}
          </p>
        </div>
      )}
    </Modal>
  )
}
