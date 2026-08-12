import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import { Button, Field, Modal } from '@/components/ui'
import { apiErrorMessage } from '@/lib/api'
import { useCreateReport, useReportReasons } from '@/features/engagement/api'

/**
 * Report a video or a comment.
 *
 * The reason vocabulary is fetched from the API rather than hardcoded, so the
 * options here cannot drift from the ones the server will accept.
 */
export default function ReportModal({ open, onClose, targetType, targetId, targetLabel }) {
  const { t } = useTranslation()
  const { data: reasons } = useReportReasons()
  const createReport = useCreateReport()

  const [reason, setReason] = useState('')
  const [details, setDetails] = useState('')

  useEffect(() => {
    if (open) {
      setReason('')
      setDetails('')
    }
  }, [open])

  const submit = async () => {
    if (!reason) return
    try {
      await createReport.mutateAsync({ targetType, targetId, reason, details })
      toast.success(t('engagement.reportSent'))
      onClose()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('engagement.reportTitle')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            onClick={submit}
            disabled={!reason}
            loading={createReport.isPending}
          >
            {t('engagement.reportSubmit')}
          </Button>
        </>
      }
    >
      {targetLabel && (
        <p className="mb-4 truncate rounded-lg bg-ink-800 px-3 py-2 text-xs text-ink-400">
          {t(`engagement.reportTarget.${targetType}`)}: {targetLabel}
        </p>
      )}

      <Field label={t('engagement.reportReason')} required>
        <div className="space-y-1.5">
          {(reasons ?? []).map((option) => (
            <label
              key={option.value}
              className={`flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 text-sm transition ${
                reason === option.value
                  ? 'border-red-500/60 bg-red-500/10'
                  : 'border-ink-700 hover:border-ink-600'
              }`}
            >
              <input
                type="radio"
                name="report-reason"
                value={option.value}
                checked={reason === option.value}
                onChange={(event) => setReason(event.target.value)}
                className="accent-red-500"
              />
              {option.label}
            </label>
          ))}
        </div>
      </Field>

      <Field label={t('engagement.reportDetails')} hint={t('common.optional')}>
        <textarea
          rows={3}
          maxLength={1000}
          className="sv-input resize-y"
          placeholder={t('engagement.reportDetailsPlaceholder')}
          value={details}
          onChange={(event) => setDetails(event.target.value)}
        />
      </Field>

      <p className="text-xs text-ink-500">{t('engagement.reportNotice')}</p>
    </Modal>
  )
}
