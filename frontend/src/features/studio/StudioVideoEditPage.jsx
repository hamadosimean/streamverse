import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowLeft, Info, Play, RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { z } from 'zod'

import StatusBadge from '@/components/StatusBadge'
import { Badge, Button, Field, LoadingBlock, ProgressBar } from '@/components/ui'
import { apiErrorMessage, apiFieldErrors } from '@/lib/api'
import { formatBytes, formatDuration } from '@/lib/format'
import { categoryLabel } from '@/lib/i18n'
import { useTranscodeProgress } from '@/hooks/useTranscodeProgress'
import {
  useCategories,
  useRetryTranscode,
  useStudioVideo,
  useUpdateVideo,
} from '@/features/videos/api'

const VISIBILITIES = ['private', 'unlisted', 'public']

export default function StudioVideoEditPage() {
  const { t, i18n } = useTranslation()
  const { videoId } = useParams()
  const navigate = useNavigate()

  const videoQuery = useStudioVideo(videoId)
  const { data: categories } = useCategories()
  const updateVideo = useUpdateVideo(videoId)
  const retryTranscode = useRetryTranscode()

  const [tags, setTags] = useState([])
  const [tagDraft, setTagDraft] = useState('')

  const video = videoQuery.data

  // Live pipeline progress while this video is still transcoding.
  const { progress } = useTranscodeProgress(videoId, {
    enabled: video?.status === 'processing',
    onTerminal: () => videoQuery.refetch(),
  })

  const schema = z.object({
    title: z
      .string()
      .min(1, t('validation.required'))
      .max(200, t('validation.max', { count: 200 })),
    description: z.string().max(5000, t('validation.max', { count: 5000 })),
    visibility: z.enum(VISIBILITIES),
    category_slug: z.string().optional(),
  })

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({ resolver: zodResolver(schema) })

  // Populate the form once the video has loaded.
  useEffect(() => {
    if (!video) return
    reset({
      title: video.title,
      description: video.description || '',
      visibility: video.visibility,
      category_slug: video.category?.slug || '',
    })
    setTags((video.tags || []).map((tag) => tag.name))
  }, [video, reset])

  const selectedVisibility = watch('visibility')

  const addTag = () => {
    const cleaned = tagDraft.trim().toLowerCase()
    if (!cleaned || tags.includes(cleaned) || tags.length >= 15) {
      setTagDraft('')
      return
    }
    setTags((current) => [...current, cleaned])
    setTagDraft('')
  }

  const onSubmit = async (values) => {
    try {
      await updateVideo.mutateAsync({
        ...values,
        category_slug: values.category_slug || null,
        tag_names: tags,
      })
      toast.success(t('studio.saved'))
    } catch (error) {
      const fields = apiFieldErrors(error)
      let matched = false
      Object.entries(fields).forEach(([key, message]) => {
        const target = key === 'category' ? 'category_slug' : key
        if (['title', 'description', 'visibility', 'category_slug'].includes(target)) {
          setError(target, { message })
          matched = true
        }
      })
      if (!matched) toast.error(apiErrorMessage(error))
    }
  }

  if (videoQuery.isLoading) return <LoadingBlock />
  if (videoQuery.isError || !video) {
    return (
      <div className="mx-auto max-w-2xl py-10 text-center text-sm text-ink-400">
        {t('common.notFound')}
      </div>
    )
  }

  const canPublish = video.status === 'ready'

  return (
    <div className="mx-auto max-w-3xl">
      <button
        type="button"
        onClick={() => navigate('/studio')}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-400 transition hover:text-ink-100"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t('studio.title')}
      </button>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">{t('studio.editTitle')}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={video.status} />
            {video.source_resolution && <Badge>{video.source_resolution}</Badge>}
            {video.duration_seconds > 0 && (
              <Badge>{formatDuration(video.duration_seconds)}</Badge>
            )}
          </div>
        </div>
        {video.status === 'ready' && (
          <Link to={`/watch/${video.id}`}>
            <Button variant="secondary" size="sm">
              <Play className="size-4" />
              {t('player.play')}
            </Button>
          </Link>
        )}
      </header>

      {/* -------------------------------------------------- pipeline state */}
      {video.status === 'processing' && (
        <div className="mb-6 rounded-card border border-amber-500/30 bg-amber-500/5 p-4">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="text-amber-200">
              {t(`video.stage.${progress?.stage ?? video.processing_stage}`)}
              {progress?.detail && ` — ${progress.detail}`}
            </span>
            <span className="tabular-nums text-amber-200">
              {progress?.percent ?? video.processing_progress}%
            </span>
          </div>
          <ProgressBar value={progress?.percent ?? video.processing_progress} />
        </div>
      )}

      {video.status === 'failed' && (
        <div className="mb-6 rounded-card border border-red-500/30 bg-red-500/5 p-4">
          <p className="mb-1 text-xs font-semibold text-red-200">
            {t('video.failureReason')}
          </p>
          <p className="mb-3 whitespace-pre-line text-xs text-red-300">
            {video.failure_reason}
          </p>
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="secondary"
              loading={retryTranscode.isPending}
              onClick={async () => {
                try {
                  await retryTranscode.mutateAsync(video.id)
                  toast.success(t('studio.retryQueued'))
                  videoQuery.refetch()
                } catch (error) {
                  toast.error(apiErrorMessage(error))
                }
              }}
            >
              <RefreshCw className="size-4" />
              {t('common.retry')}
            </Button>
            <span className="text-xs text-ink-400">
              {t('video.attempts')}: {video.transcode_attempts}
            </span>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- form */}
      <form onSubmit={handleSubmit(onSubmit)} className="sv-card p-5" noValidate>
        <Field label={t('form.title')} error={errors.title?.message} required>
          <input type="text" className="sv-input" maxLength={200} {...register('title')} />
        </Field>

        <Field label={t('form.description')} error={errors.description?.message}>
          <textarea rows={5} className="sv-input resize-y" {...register('description')} />
        </Field>

        <Field label={t('form.category')} error={errors.category_slug?.message}>
          <select className="sv-input" {...register('category_slug')}>
            <option value="">{t('form.noCategory')}</option>
            {(categories ?? []).map((category) => (
              <option key={category.slug} value={category.slug}>
                {categoryLabel(category, t)}
              </option>
            ))}
          </select>
        </Field>

        <Field label={t('form.tags')} hint={t('form.tagsHint')}>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-full bg-ink-700 px-2.5 py-1 text-xs"
              >
                #{tag}
                <button
                  type="button"
                  onClick={() => setTags((current) => current.filter((item) => item !== tag))}
                  aria-label={`${t('common.delete')} ${tag}`}
                  className="text-ink-400 transition hover:text-red-400"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
          <input
            type="text"
            className="sv-input"
            placeholder={t('form.tagsPlaceholder')}
            value={tagDraft}
            maxLength={50}
            onChange={(event) => setTagDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ',') {
                event.preventDefault()
                addTag()
              }
            }}
            onBlur={addTag}
          />
        </Field>

        <Field label={t('form.visibility')} error={errors.visibility?.message}>
          <div className="space-y-2">
            {VISIBILITIES.map((value) => {
              const disabled = value !== 'private' && !canPublish
              return (
                <label
                  key={value}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition ${
                    selectedVisibility === value
                      ? 'border-brand-500 bg-brand-500/10'
                      : 'border-ink-700 hover:border-ink-600'
                  } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
                >
                  <input
                    type="radio"
                    value={value}
                    disabled={disabled}
                    className="mt-0.5 accent-brand-500"
                    {...register('visibility')}
                  />
                  <span>
                    <span className="block text-sm font-medium">
                      {t(`video.visibility.${value}`)}
                    </span>
                    <span className="block text-xs text-ink-400">
                      {t(`video.visibility.${value}Hint`)}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
          {!canPublish && (
            <p className="mt-2 flex items-start gap-2 text-xs text-amber-300">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {t('video.publishBlocked')}
            </p>
          )}
        </Field>

        <div className="mt-6 flex gap-3">
          <Button type="submit" loading={isSubmitting || updateVideo.isPending}>
            {t('common.save')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={!isDirty}
            onClick={() =>
              reset({
                title: video.title,
                description: video.description || '',
                visibility: video.visibility,
                category_slug: video.category?.slug || '',
              })
            }
          >
            {t('common.cancel')}
          </Button>
        </div>
      </form>

      {/* --------------------------------------------------- technical facts */}
      <section className="mt-5 rounded-card border border-ink-800 bg-ink-850 p-4 text-xs text-ink-400">
        <dl className="grid gap-2 sm:grid-cols-2">
          <div>
            <dt className="text-ink-500">{t('watch.sourceResolution')}</dt>
            <dd className="text-ink-200">{video.source_resolution || '—'}</dd>
          </div>
          <div>
            <dt className="text-ink-500">Fichier source</dt>
            <dd className="truncate text-ink-200">
              {video.original_filename} ({formatBytes(video.original_size_bytes, i18n.language)})
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-ink-500">{t('watch.renditions')}</dt>
            <dd className="mt-1 flex flex-wrap gap-1.5">
              {video.renditions?.length ? (
                video.renditions.map((rendition) => (
                  <Badge key={rendition.label}>
                    {rendition.label} · {rendition.segment_count} segments ·{' '}
                    {formatBytes(rendition.file_size, i18n.language)}
                  </Badge>
                ))
              ) : (
                <span className="text-ink-200">—</span>
              )}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  )
}
