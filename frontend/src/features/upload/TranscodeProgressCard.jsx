import { CheckCircle2, ExternalLink, RadioTower, XCircle } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Badge, ProgressBar } from '@/components/ui'
import { videoKeys } from '@/features/videos/api'
import { useTranscodeProgress } from '@/hooks/useTranscodeProgress'

/**
 * Post-upload pipeline progress for one video.
 *
 * The bar is weighted server-side across the pipeline stages (probe /
 * transcode / package / thumbnails / publish), so it advances at a rate that
 * roughly matches real wall-clock rather than jumping between equal fifths.
 */
export default function TranscodeProgressCard({ videoId, title }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const { progress, connected } = useTranscodeProgress(videoId, {
    onTerminal: () => {
      queryClient.invalidateQueries({ queryKey: videoKeys.studioList })
      queryClient.invalidateQueries({ queryKey: videoKeys.studioStats })
      queryClient.invalidateQueries({ queryKey: videoKeys.feed })
    },
  })

  const status = progress?.status ?? 'processing'
  const percent = progress?.percent ?? 0
  const stage = progress?.stage ?? 'queued'

  return (
    <div className="rounded-card border border-ink-800 bg-ink-850 p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{title}</p>
          <p className="mt-0.5 text-xs text-ink-400">
            {status === 'ready'
              ? t('video.status.ready')
              : status === 'failed'
                ? t('video.status.failed')
                : t(`video.stage.${stage}`)}
            {progress?.detail && status !== 'failed' && ` — ${progress.detail}`}
          </p>
        </div>

        {status === 'ready' && <CheckCircle2 className="size-5 shrink-0 text-emerald-400" />}
        {status === 'failed' && <XCircle className="size-5 shrink-0 text-red-400" />}
        {status === 'processing' && (
          <Badge tone={connected ? 'brand' : 'neutral'}>
            <RadioTower className="size-3" aria-hidden />
            {percent}%
          </Badge>
        )}
      </div>

      <ProgressBar
        value={status === 'ready' ? 100 : percent}
        tone={status === 'failed' ? 'danger' : status === 'ready' ? 'success' : 'brand'}
      />

      {status === 'failed' && progress?.detail && (
        <p className="mt-2 rounded border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-300">
          {progress.detail}
        </p>
      )}

      <div className="mt-3 flex gap-3 text-xs">
        <Link
          to={`/studio/videos/${videoId}`}
          className="inline-flex items-center gap-1 text-brand-300 transition hover:underline"
        >
          {t('upload.openInStudio')}
          <ExternalLink className="size-3" aria-hidden />
        </Link>
        {status === 'ready' && (
          <Link
            to={`/watch/${videoId}`}
            className="inline-flex items-center gap-1 text-brand-300 transition hover:underline"
          >
            {t('player.play')}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        )}
      </div>
    </div>
  )
}
