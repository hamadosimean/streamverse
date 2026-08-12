import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import { Button, Field, Modal } from '@/components/ui'
import { apiErrorMessage, apiFieldErrors } from '@/lib/api'
import { categoryLabel } from '@/lib/i18n'
import { useSaveCampaign } from '@/features/monetization/api'
import { useCategories } from '@/features/videos/api'

const EMPTY = {
  advertiser_name: '',
  title: '',
  placement: 'pre_roll',
  duration_seconds: 10,
  skippable_after_seconds: 5,
  mid_roll_position: 0.5,
  impression_cap: 0,
  weight: 1,
  click_url: '',
  status: 'draft',
  start_date: '',
  end_date: '',
  category_slugs: [],
}

/** Local datetime string the `datetime-local` input understands. */
function toLocalInput(value) {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

export default function CampaignFormModal({ open, campaign, onClose }) {
  const { t } = useTranslation()
  const { data: categories } = useCategories()
  const save = useSaveCampaign()

  const [values, setValues] = useState(EMPTY)
  const [creativeFile, setCreativeFile] = useState(null)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (!open) return
    setErrors({})
    setCreativeFile(null)
    setValues(
      campaign
        ? {
            ...EMPTY,
            ...campaign,
            start_date: toLocalInput(campaign.start_date),
            end_date: toLocalInput(campaign.end_date),
            category_slugs: campaign.category_slugs ?? [],
          }
        : {
            ...EMPTY,
            start_date: toLocalInput(new Date()),
            end_date: toLocalInput(new Date(Date.now() + 30 * 86400000)),
          },
    )
  }, [open, campaign])

  const set = (key, value) => setValues((current) => ({ ...current, [key]: value }))

  const submit = async () => {
    setErrors({})
    try {
      // Only the writable fields. Spreading `values` would also post the
      // server-owned ones copied in from the campaign (counters, id, timestamps);
      // DRF ignores them, but sending them invites confusion later.
      const body = {
        advertiser_name: values.advertiser_name,
        title: values.title,
        placement: values.placement,
        duration_seconds: values.duration_seconds,
        skippable_after_seconds: values.skippable_after_seconds,
        mid_roll_position: values.mid_roll_position,
        impression_cap: values.impression_cap,
        weight: values.weight,
        click_url: values.click_url,
        status: values.status,
        start_date: new Date(values.start_date).toISOString(),
        end_date: new Date(values.end_date).toISOString(),
      }

      let payload
      if (creativeFile) {
        // A file forces multipart. Arrays go as repeated keys — FormData has no
        // notion of a list value.
        payload = new FormData()
        Object.entries(body).forEach(([key, value]) => {
          if (value !== null && value !== undefined && value !== '') {
            payload.append(key, value)
          }
        })
        values.category_slugs.forEach((slug) =>
          payload.append('category_slugs', slug))
        payload.append('creative', creativeFile)
        payload.append('creative_is_video',
                       creativeFile.type.startsWith('video/') ? 'true' : 'false')
      } else {
        // No file: JSON, which keeps category_slugs a real array.
        payload = { ...body, category_slugs: values.category_slugs }
      }

      await save.mutateAsync({ id: campaign?.id, payload })
      toast.success(t('ads.admin.saved'))
      onClose()
    } catch (error) {
      const fields = apiFieldErrors(error)
      if (Object.keys(fields).length) setErrors(fields)
      else toast.error(apiErrorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={campaign ? t('ads.admin.editCampaign') : t('ads.admin.newCampaign')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} loading={save.isPending}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="max-h-[60vh] space-y-0 overflow-y-auto pr-1">
        <Field label={t('ads.admin.advertiser')} error={errors.advertiser_name} required>
          <input
            className="sv-input"
            value={values.advertiser_name}
            onChange={(event) => set('advertiser_name', event.target.value)}
          />
        </Field>

        <Field label={t('form.title')} error={errors.title} required>
          <input
            className="sv-input"
            value={values.title}
            onChange={(event) => set('title', event.target.value)}
          />
        </Field>

        <Field
          label={t('ads.admin.creative')}
          error={errors.creative}
          hint={campaign ? t('ads.admin.creativeReplaceHint') : t('ads.admin.creativeHint')}
          required={!campaign}
        >
          {/* Show what is currently in use, so "replace" is an informed choice
              rather than a guess at what is already there. */}
          {campaign?.creative_url && !creativeFile && (
            <div className="mb-2 flex items-center gap-3 rounded-lg border border-ink-700 bg-ink-800 p-2">
              {campaign.creative_is_video ? (
                // eslint-disable-next-line jsx-a11y/media-has-caption
                <video src={campaign.creative_url} muted
                       className="h-14 w-24 rounded object-cover" />
              ) : (
                <img src={campaign.creative_url} alt=""
                     className="h-14 w-24 rounded object-cover" />
              )}
              <span className="text-xs text-ink-400">{t('ads.admin.currentCreative')}</span>
            </div>
          )}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,video/mp4"
            className="sv-input"
            onChange={(event) => setCreativeFile(event.target.files?.[0] ?? null)}
          />
          {creativeFile && (
            <p className="mt-1 text-xs text-emerald-300">
              {t('ads.admin.creativeSelected', { name: creativeFile.name })}
            </p>
          )}
        </Field>

        <Field label={t('ads.admin.clickUrl')} error={errors.click_url}>
          <input
            type="url"
            className="sv-input"
            placeholder="https://…"
            value={values.click_url}
            onChange={(event) => set('click_url', event.target.value)}
          />
        </Field>

        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label={t('ads.admin.placement')} error={errors.placement}>
            <select
              className="sv-input"
              value={values.placement}
              onChange={(event) => set('placement', event.target.value)}
            >
              <option value="pre_roll">{t('ads.placement.pre_roll')}</option>
              <option value="mid_roll">{t('ads.placement.mid_roll')}</option>
            </select>
          </Field>

          <Field label={t('ads.admin.status.label')} error={errors.status}>
            <select
              className="sv-input"
              value={values.status}
              onChange={(event) => set('status', event.target.value)}
            >
              {['draft', 'active', 'paused', 'ended'].map((value) => (
                <option key={value} value={value}>
                  {t(`ads.admin.status.${value}`)}
                </option>
              ))}
            </select>
          </Field>

          <Field label={t('ads.admin.duration')} error={errors.duration_seconds}>
            <input
              type="number"
              min="3"
              max="120"
              className="sv-input"
              value={values.duration_seconds}
              onChange={(event) => set('duration_seconds', Number(event.target.value))}
            />
          </Field>

          <Field
            label={t('ads.admin.skipAfter')}
            hint={t('ads.admin.skipAfterHint')}
            error={errors.skippable_after_seconds}
          >
            <input
              type="number"
              min="0"
              max="60"
              className="sv-input"
              value={values.skippable_after_seconds}
              onChange={(event) =>
                set('skippable_after_seconds', Number(event.target.value))}
            />
          </Field>

          <Field label={t('ads.admin.startDate')} error={errors.start_date} required>
            <input
              type="datetime-local"
              className="sv-input"
              value={values.start_date}
              onChange={(event) => set('start_date', event.target.value)}
            />
          </Field>

          <Field label={t('ads.admin.endDate')} error={errors.end_date} required>
            <input
              type="datetime-local"
              className="sv-input"
              value={values.end_date}
              onChange={(event) => set('end_date', event.target.value)}
            />
          </Field>

          <Field
            label={t('ads.admin.cap')}
            hint={t('ads.admin.capHint')}
            error={errors.impression_cap}
          >
            <input
              type="number"
              min="0"
              className="sv-input"
              value={values.impression_cap}
              onChange={(event) => set('impression_cap', Number(event.target.value))}
            />
          </Field>

          <Field
            label={t('ads.admin.weight')}
            hint={t('ads.admin.weightHint')}
            error={errors.weight}
          >
            <input
              type="number"
              min="1"
              max="100"
              className="sv-input"
              value={values.weight}
              onChange={(event) => set('weight', Number(event.target.value))}
            />
          </Field>
        </div>

        {values.placement === 'mid_roll' && (
          <Field
            label={t('ads.admin.midRollPosition')}
            hint={t('ads.admin.midRollPositionHint')}
            error={errors.mid_roll_position}
          >
            <input
              type="number"
              min="0.05"
              max="0.95"
              step="0.05"
              className="sv-input"
              value={values.mid_roll_position}
              onChange={(event) => set('mid_roll_position', Number(event.target.value))}
            />
          </Field>
        )}

        <Field label={t('ads.admin.targeting')} hint={t('ads.admin.targetingHint')}>
          <div className="flex flex-wrap gap-1.5">
            {(categories ?? []).map((category) => {
              const selected = values.category_slugs.includes(category.slug)
              return (
                <button
                  key={category.slug}
                  type="button"
                  onClick={() =>
                    set(
                      'category_slugs',
                      selected
                        ? values.category_slugs.filter((s) => s !== category.slug)
                        : [...values.category_slugs, category.slug],
                    )}
                  className={`rounded-full border px-3 py-1.5 text-xs transition ${
                    selected
                      ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                      : 'border-ink-700 text-ink-300 hover:border-ink-600'
                  }`}
                >
                  {categoryLabel(category, t)}
                </button>
              )
            })}
          </div>
        </Field>
      </div>
    </Modal>
  )
}
