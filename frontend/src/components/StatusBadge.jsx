import { AlertCircle, CheckCircle2, Loader2, ShieldOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui'

const STATUS_CONFIG = {
  processing: { tone: 'warning', icon: Loader2, spin: true },
  ready: { tone: 'success', icon: CheckCircle2 },
  failed: { tone: 'danger', icon: AlertCircle },
  taken_down: { tone: 'neutral', icon: ShieldOff },
}

/** Transcoding status, rendered identically everywhere it appears. */
export default function StatusBadge({ status }) {
  const { t } = useTranslation()
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.processing
  const Icon = config.icon

  return (
    <Badge tone={config.tone}>
      <Icon className={`size-3 ${config.spin ? 'animate-spin' : ''}`} aria-hidden />
      {t(`video.status.${status}`)}
    </Badge>
  )
}

const VISIBILITY_TONES = { public: 'success', unlisted: 'warning', private: 'neutral' }

export function VisibilityBadge({ visibility }) {
  const { t } = useTranslation()
  return (
    <Badge tone={VISIBILITY_TONES[visibility] ?? 'neutral'}>
      {t(`video.visibility.${visibility}`)}
    </Badge>
  )
}
