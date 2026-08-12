import {
  CloudUpload,
  FileVideo,
  Info,
  Pause,
  Play,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import TranscodeProgressCard from '@/features/upload/TranscodeProgressCard'
import { Button, Field, ProgressBar } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'
import { useUploadStore } from '@/stores/useUploadStore'

// Kept in step with backend `ALLOWED_VIDEO_MIME_TYPES`; the server re-validates
// by sniffing the file's real magic bytes, so this is purely a courtesy check.
const ACCEPTED = [
  'video/mp4',
  'video/quicktime',
  'video/x-matroska',
  'video/webm',
  'video/x-msvideo',
  'video/mpeg',
  'video/3gpp',
  'video/x-flv',
]
const MAX_BYTES = 5 * 1024 * 1024 * 1024

export default function UploadPage() {
  const { t, i18n } = useTranslation()
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  const { queue, start, pause, resume, cancel, remove, clearFinished } = useUploadStore()

  const acceptFile = (candidate) => {
    if (!candidate) return
    if (candidate.size > MAX_BYTES) {
      toast.error(t('upload.fileTooLarge', { max: formatBytes(MAX_BYTES, i18n.language) }))
      return
    }
    // Some browsers report an empty type for .mkv/.flv; let the server decide
    // rather than blocking a legitimate file on a missing MIME string.
    if (candidate.type && !ACCEPTED.includes(candidate.type)) {
      toast.error(t('upload.invalidType'))
      return
    }
    setFile(candidate)
    if (!title) setTitle(candidate.name.replace(/\.[^.]+$/, ''))
  }

  const beginUpload = () => {
    if (!file) return
    start(file, { title: title.trim() || file.name, description: description.trim() })
    setFile(null)
    setTitle('')
    setDescription('')
    if (inputRef.current) inputRef.current.value = ''
  }

  const processing = queue.filter((item) => item.status === 'processing' && item.videoId)
  const active = queue.filter((item) => item.status !== 'processing')

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">{t('upload.title')}</h1>
        <p className="mt-1 text-sm text-ink-400">{t('upload.subtitle')}</p>
      </header>

      {/* ---------------------------------------------------------- dropzone */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) =>
          ['Enter', ' '].includes(event.key) && inputRef.current?.click()
        }
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          acceptFile(event.dataTransfer.files?.[0])
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center gap-3 rounded-card border-2 border-dashed px-6 py-12 text-center transition',
          dragging
            ? 'border-brand-500 bg-brand-500/10'
            : 'border-ink-700 hover:border-ink-600 hover:bg-ink-850',
        )}
      >
        <CloudUpload
          className={cn('size-12', dragging ? 'text-brand-400' : 'text-ink-600')}
          aria-hidden
        />
        <p className="text-sm font-medium">
          {dragging ? t('upload.dropzoneActive') : t('upload.dropzone')}
        </p>
        <p className="text-xs text-ink-400">
          {t('upload.dropzoneHint', { max: formatBytes(MAX_BYTES, i18n.language) })}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(',')}
          className="hidden"
          onChange={(event) => acceptFile(event.target.files?.[0])}
        />
      </div>

      {/* ------------------------------------------------------ metadata form */}
      {file && (
        <div className="sv-card mt-5 p-5">
          <div className="mb-4 flex items-center gap-3 rounded-lg bg-ink-800 p-3">
            <FileVideo className="size-8 shrink-0 text-brand-400" aria-hidden />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-ink-400">
                {formatBytes(file.size, i18n.language)}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto"
              onClick={() => setFile(null)}
              aria-label={t('common.cancel')}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>

          <Field label={t('upload.videoTitle')} required>
            <input
              type="text"
              className="sv-input"
              maxLength={200}
              placeholder={t('upload.videoTitlePlaceholder')}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>

          <Field label={t('upload.description')}>
            <textarea
              rows={3}
              className="sv-input resize-y"
              maxLength={5000}
              placeholder={t('upload.descriptionPlaceholder')}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>

          <p className="mb-4 flex items-start gap-2 rounded-lg border border-ink-700 bg-ink-800 p-3 text-xs text-ink-400">
            <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
            {t('upload.pipelineNote')}
          </p>

          <Button onClick={beginUpload} disabled={!title.trim()}>
            <UploadCloud className="size-4" />
            {t('upload.startUpload')}
          </Button>
        </div>
      )}

      {/* -------------------------------------------------------- upload queue */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('upload.queue')}</h2>
          {queue.length > 0 && (
            <Button variant="ghost" size="sm" onClick={clearFinished}>
              {t('upload.clearFinished')}
            </Button>
          )}
        </div>

        {queue.length === 0 && (
          <p className="rounded-card border border-dashed border-ink-700 px-4 py-8 text-center text-sm text-ink-400">
            {t('upload.queueEmpty')}
          </p>
        )}

        <div className="space-y-3">
          {active.map((item) => (
            <div
              key={item.id}
              className="rounded-card border border-ink-800 bg-ink-850 p-4"
            >
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{item.title}</p>
                  <p className="text-xs text-ink-400">
                    {formatBytes(item.bytesUploaded, i18n.language)} /{' '}
                    {formatBytes(item.size, i18n.language)} —{' '}
                    {item.status === 'paused' ? t('upload.paused') : t('upload.uploading')}
                  </p>
                </div>

                <div className="flex shrink-0 gap-1">
                  {item.status === 'uploading' && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => pause(item.id)}
                      aria-label={t('upload.pause')}
                    >
                      <Pause className="size-4" />
                    </Button>
                  )}
                  {(item.status === 'paused' || item.status === 'error') && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => resume(item.id)}
                      aria-label={t('upload.resume')}
                    >
                      <Play className="size-4" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() =>
                      item.status === 'error' ? remove(item.id) : cancel(item.id)
                    }
                    aria-label={t('upload.cancel')}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>

              <ProgressBar
                value={item.percent}
                tone={item.status === 'error' ? 'danger' : 'brand'}
              />

              {item.error && (
                <p className="mt-2 rounded border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-300">
                  {item.error}
                </p>
              )}
            </div>
          ))}

          {/* Transferred; now watching the server-side pipeline over WebSocket. */}
          {processing.map((item) => (
            <TranscodeProgressCard
              key={item.id}
              videoId={item.videoId}
              title={item.title}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
