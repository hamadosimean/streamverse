import {
  AlertTriangle,
  Check,
  Copy,
  Eye,
  EyeOff,
  Film,
  RadioTower,
  RefreshCw,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'

import StatusBadge from '@/components/StatusBadge'
import { Badge, Button, Field, LoadingBlock, Modal } from '@/components/ui'
import GoLivePanel from '@/features/live/GoLivePanel'
import { apiErrorMessage } from '@/lib/api'
import { formatBytes, formatDuration, formatRelative } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'
import {
  useMyLiveChannel,
  useMyLiveSessions,
  useRotateStreamKey,
  useUpdateMyLiveChannel,
} from '@/features/live/api'
import { useCategories } from '@/features/videos/api'

function SecretField({ label, value, hint }) {
  const { t } = useTranslation()
  const [revealed, setRevealed] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error(t('common.error'))
    }
  }

  return (
    <Field label={label} hint={hint}>
      <div className="flex gap-2">
        <input
          type={revealed ? 'text' : 'password'}
          readOnly
          value={value}
          className="sv-input font-mono text-xs"
          onFocus={(event) => event.target.select()}
        />
        <Button
          variant="secondary"
          size="icon"
          onClick={() => setRevealed((v) => !v)}
          aria-label={revealed ? t('live.hideKey') : t('live.revealKey')}
        >
          {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
        <Button variant="secondary" size="icon" onClick={copy} aria-label={t('live.copy')}>
          {copied ? <Check className="size-4 text-emerald-400" /> : <Copy className="size-4" />}
        </Button>
      </div>
    </Field>
  )
}

export default function StudioLivePage() {
  const { t, i18n } = useTranslation()
  const channelQuery = useMyLiveChannel()
  const sessionsQuery = useMyLiveSessions()
  const { data: categories } = useCategories()
  const update = useUpdateMyLiveChannel()
  const rotate = useRotateStreamKey()

  const [confirmRotate, setConfirmRotate] = useState(false)
  const [form, setForm] = useState(null)

  if (channelQuery.isLoading) return <LoadingBlock />
  if (channelQuery.isError) {
    return (
      <p className="py-10 text-center text-sm text-ink-400">{t('common.errorRetry')}</p>
    )
  }

  const channel = channelQuery.data
  const values = form ?? {
    title: channel.title || '',
    description: channel.description || '',
    category_slug: channel.category_slug || '',
    chat_enabled: channel.chat_enabled,
    record_sessions: channel.record_sessions,
  }
  const setValue = (key, value) => setForm({ ...values, [key]: value })

  const save = async () => {
    try {
      await update.mutateAsync({ ...values, category_slug: values.category_slug || null })
      setForm(null)
      toast.success(t('studio.saved'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const doRotate = async () => {
    try {
      await rotate.mutateAsync()
      toast.success(t('live.keyRotated'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setConfirmRotate(false)
    }
  }

  const sessions = sessionsQuery.data?.results ?? []

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <RadioTower className="size-6 text-red-400" aria-hidden />
            {t('live.studioTitle')}
          </h1>
          <p className="mt-1 text-sm text-ink-400">{t('live.studioSubtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={channel.status === 'live' ? 'danger' : 'neutral'}>
            {t(`live.status.${channel.status}`)}
          </Badge>
          {channel.status === 'live' && (
            <Link to={`/live/${channel.slug}`}>
              <Button size="sm" variant="secondary">{t('live.viewStream')}</Button>
            </Link>
          )}
        </div>
      </header>

      {/* Broadcasting from this device is the path most people want, so it
          leads; OBS keeps its section below for anyone with a real setup. */}
      {channel.can_broadcast_from_browser && (
        <GoLivePanel channel={channel} onStatusChange={() => channelQuery.refetch()} />
      )}

      {/* ---------------------------------------------------- OBS settings */}
      <section className="sv-card mb-5 p-5">
        <h2 className="mb-1 text-sm font-semibold">{t('live.obsTitle')}</h2>
        <p className="mb-4 text-xs text-ink-400">{t('live.obsHint')}</p>

        <Field label={t('live.serverUrl')} hint={t('live.serverUrlHint')}>
          <input readOnly value={channel.ingest_url} className="sv-input font-mono text-xs" />
        </Field>

        <SecretField
          label={t('live.streamKeyField')}
          value={channel.obs_stream_key}
          hint={t('live.streamKeyHint')}
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="danger" size="sm" onClick={() => setConfirmRotate(true)}>
            <RefreshCw className="size-4" />
            {t('live.rotateKey')}
          </Button>
          <span className="text-xs text-ink-500">
            {t('live.rotatedAt', {
              date: formatRelative(channel.stream_key_rotated_at, i18n.language),
            })}
          </span>
        </div>

        <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {t('live.keySecrecyWarning')}
        </p>
      </section>

      {/* ------------------------------------------------ channel settings */}
      <section className="sv-card mb-5 p-5">
        <h2 className="mb-4 text-sm font-semibold">{t('live.channelSettings')}</h2>

        <Field label={t('form.title')}>
          <input
            className="sv-input"
            maxLength={200}
            value={values.title}
            onChange={(event) => setValue('title', event.target.value)}
          />
        </Field>

        <Field label={t('form.description')}>
          <textarea
            rows={3}
            className="sv-input resize-y"
            maxLength={2000}
            value={values.description}
            onChange={(event) => setValue('description', event.target.value)}
          />
        </Field>

        <Field label={t('form.category')}>
          <select
            className="sv-input"
            value={values.category_slug}
            onChange={(event) => setValue('category_slug', event.target.value)}
          >
            <option value="">{t('form.noCategory')}</option>
            {(categories ?? []).map((category) => (
              <option key={category.slug} value={category.slug}>
                {categoryLabel(category, t)}
              </option>
            ))}
          </select>
        </Field>

        <div className="mb-4 space-y-2">
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-ink-700 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 accent-brand-500"
              checked={values.chat_enabled}
              onChange={(event) => setValue('chat_enabled', event.target.checked)}
            />
            <span>
              <span className="block font-medium">{t('live.chatEnabled')}</span>
              <span className="block text-xs text-ink-400">{t('live.chatEnabledHint')}</span>
            </span>
          </label>

          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-ink-700 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 accent-brand-500"
              checked={values.record_sessions}
              onChange={(event) => setValue('record_sessions', event.target.checked)}
            />
            <span>
              <span className="block font-medium">{t('live.recordSessions')}</span>
              <span className="block text-xs text-ink-400">{t('live.recordSessionsHint')}</span>
            </span>
          </label>
        </div>

        <Button onClick={save} loading={update.isPending} disabled={!form}>
          {t('common.save')}
        </Button>
      </section>

      {/* --------------------------------------------------- past sessions */}
      <section className="sv-card p-5">
        <h2 className="mb-4 text-sm font-semibold">{t('live.pastSessions')}</h2>

        {sessions.length === 0 ? (
          <p className="py-6 text-center text-xs text-ink-500">{t('live.noSessions')}</p>
        ) : (
          <div className="space-y-2">
            {sessions.map((session) => (
              <div
                key={session.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-800/50 p-3 text-xs"
              >
                <span className="font-medium text-ink-200">
                  {formatRelative(session.started_at, i18n.language)}
                </span>
                <span className="text-ink-400">
                  {formatDuration(session.duration_seconds)}
                </span>
                <span className="text-ink-400">
                  {t('live.peak', { count: session.peak_viewer_count })}
                </span>
                {session.recorded_size_bytes > 0 && (
                  <span className="text-ink-400">
                    {formatBytes(session.recorded_size_bytes, i18n.language)}
                  </span>
                )}

                <span className="ml-auto">
                  {session.converted_video_id ? (
                    <Link
                      to={`/studio/videos/${session.converted_video_id}`}
                      className="inline-flex items-center gap-1 text-brand-300 hover:underline"
                    >
                      <Film className="size-3.5" aria-hidden />
                      {t('live.recordingReady')}
                    </Link>
                  ) : session.conversion_error ? (
                    <span className="text-red-300" title={session.conversion_error}>
                      {t('live.recordingFailed')}
                    </span>
                  ) : session.ended_at ? (
                    <StatusBadge status="processing" />
                  ) : (
                    <Badge tone="danger">{t('live.badge')}</Badge>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}

        <p className="mt-4 text-xs text-ink-500">{t('live.recordingNote')}</p>
      </section>

      <Modal
        open={confirmRotate}
        onClose={() => setConfirmRotate(false)}
        title={t('live.rotateKey')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmRotate(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" loading={rotate.isPending} onClick={doRotate}>
              {t('live.rotateConfirm')}
            </Button>
          </>
        }
      >
        {t('live.rotateWarning')}
      </Modal>
    </div>
  )
}
