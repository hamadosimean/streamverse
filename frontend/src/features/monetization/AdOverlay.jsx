import { ExternalLink, SkipForward } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { reportAdEvent } from '@/features/monetization/api'

/**
 * A single ad break, rendered over the player.
 *
 * First-party rotation: this shows one of *our* campaign creatives. There is no
 * VAST document, no third-party ad script and no tracking pixel — nothing here
 * loads anything from outside this deployment.
 *
 * The countdown and the skip gate are cosmetic. Impression accounting is
 * server-side: the impression row was already written when the plan was
 * selected, so a viewer who blocks this component still counted as served.
 */
export default function AdOverlay({ ad, onFinish }) {
  const { t } = useTranslation()
  const videoRef = useRef(null)
  const startedAt = useRef(Date.now())
  const [remaining, setRemaining] = useState(ad.duration_seconds)
  const [elapsed, setElapsed] = useState(0)

  const canSkip =
    ad.skippable_after_seconds > 0 && elapsed >= ad.skippable_after_seconds

  useEffect(() => {
    startedAt.current = Date.now()
    const timer = setInterval(() => {
      const seconds = Math.floor((Date.now() - startedAt.current) / 1000)
      setElapsed(seconds)
      setRemaining(Math.max(0, ad.duration_seconds - seconds))
      if (seconds >= ad.duration_seconds) {
        clearInterval(timer)
        reportAdEvent(ad.impression_id, {
          watched_seconds: seconds,
          completed: true,
        })
        onFinish?.()
      }
    }, 250)
    return () => clearInterval(timer)
  }, [ad, onFinish])

  const skip = () => {
    reportAdEvent(ad.impression_id, { watched_seconds: elapsed, skipped: true })
    onFinish?.()
  }

  const click = () => {
    reportAdEvent(ad.impression_id, { watched_seconds: elapsed, clicked: true })
    if (ad.click_url) window.open(ad.click_url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-black">
      <button
        type="button"
        onClick={click}
        className="relative flex flex-1 items-center justify-center"
        aria-label={ad.title}
      >
        {ad.creative_is_video ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video
            ref={videoRef}
            src={ad.creative_url}
            autoPlay
            playsInline
            className="size-full object-contain"
          />
        ) : (
          <img
            src={ad.creative_url}
            alt={ad.title}
            className="size-full object-contain"
          />
        )}
      </button>

      <div className="flex items-center gap-3 bg-black/90 px-4 py-2.5 text-white">
        <span className="rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold uppercase text-black">
          {t('ads.label')}
        </span>
        <span className="min-w-0 truncate text-xs">
          <span className="text-ink-300">{ad.advertiser_name}</span>
          <span className="mx-1.5 text-ink-500">·</span>
          {ad.title}
        </span>

        {ad.click_url && (
          <button
            type="button"
            onClick={click}
            className="hidden items-center gap-1 rounded border border-white/30 px-2 py-1 text-[11px] transition hover:bg-white/10 sm:inline-flex"
          >
            {t('ads.learnMore')}
            <ExternalLink className="size-3" aria-hidden />
          </button>
        )}

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs tabular-nums text-ink-300">
            {t('ads.remaining', { seconds: remaining })}
          </span>
          {ad.skippable_after_seconds > 0 && (
            <button
              type="button"
              onClick={skip}
              disabled={!canSkip}
              className="inline-flex items-center gap-1.5 rounded border border-white/30 px-2.5 py-1 text-xs transition enabled:hover:bg-white/10 disabled:opacity-50"
            >
              {canSkip
                ? t('ads.skip')
                : t('ads.skipIn', {
                    seconds: ad.skippable_after_seconds - elapsed,
                  })}
              <SkipForward className="size-3.5" aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
