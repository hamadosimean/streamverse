import Hls from 'hls.js'
import { Maximize, Minimize, Pause, Play, RotateCcw, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { usePlayerStore } from '@/stores/usePlayerStore'

/**
 * Live player — separate from the VOD player on purpose.
 *
 * A live stream has no duration, no seek bar and no scrubbing previews; the only
 * meaningful position is "now". Reusing the VOD player would mean disabling half
 * its controls and explaining why the timeline is frozen.
 *
 * The distinctive behaviour here is **drift recovery**: a tab that was
 * backgrounded, or a network stall, leaves the player replaying a window from
 * minutes ago. Live playback that silently falls behind is worse than none, so
 * this seeks back to the live edge whenever it drifts too far.
 */
const MAX_DRIFT_SECONDS = 12

export default function LivePlayer({ src, poster, isLive }) {
  const { t } = useTranslation()
  const containerRef = useRef(null)
  const videoRef = useRef(null)
  const hlsRef = useRef(null)

  const { volume, muted, setVolume, toggleMuted } = usePlayerStore()
  const [playing, setPlaying] = useState(false)
  const [buffering, setBuffering] = useState(false)
  const [atLiveEdge, setAtLiveEdge] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  const [error, setError] = useState(null)

  const seekToLive = useCallback(() => {
    const video = videoRef.current
    const hls = hlsRef.current
    if (!video) return
    if (hls) {
      video.currentTime = hls.liveSyncPosition ?? video.duration ?? 0
    } else if (video.seekable.length) {
      video.currentTime = video.seekable.end(video.seekable.length - 1)
    }
    video.play().catch(() => {})
  }, [])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !src || !isLive) return undefined

    setError(null)

    if (!Hls.isSupported()) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = src
        return () => {
          video.removeAttribute('src')
          video.load()
        }
      }
      setError(t('player.notSupported'))
      return undefined
    }

    const hls = new Hls({
      lowLatencyMode: false,
      // Sit ~3 segments behind the edge: close enough to feel live, far enough
      // that one slow segment does not stall playback.
      liveSyncDurationCount: 3,
      liveMaxLatencyDurationCount: 10,
      backBufferLength: 30,
      enableWorker: true,
      // A live playlist is rewritten constantly; a failed refresh is normal and
      // should be retried rather than treated as fatal.
      manifestLoadingMaxRetry: 6,
      levelLoadingMaxRetry: 6,
      fragLoadingMaxRetry: 6,
    })
    hlsRef.current = hls

    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
        hls.startLoad()
      } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError()
      } else {
        setError(t('player.errorHint'))
        hls.destroy()
      }
    })

    hls.loadSource(src)
    hls.attachMedia(video)

    return () => {
      hls.destroy()
      hlsRef.current = null
    }
  }, [src, isLive, t])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    video.volume = volume
    video.muted = muted

    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onWaiting = () => setBuffering(true)
    const onPlaying = () => setBuffering(false)
    const onTimeUpdate = () => {
      const hls = hlsRef.current
      const edge = hls?.liveSyncPosition
      if (edge == null) return
      setAtLiveEdge(edge - video.currentTime < MAX_DRIFT_SECONDS)
    }

    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('waiting', onWaiting)
    video.addEventListener('playing', onPlaying)
    video.addEventListener('timeupdate', onTimeUpdate)
    return () => {
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('waiting', onWaiting)
      video.removeEventListener('playing', onPlaying)
      video.removeEventListener('timeupdate', onTimeUpdate)
    }
  }, [volume, muted])

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) seekToLive()
    else video.pause()
  }

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen()
    else containerRef.current?.requestFullscreen?.()
  }

  if (!isLive) {
    return (
      <div className="grid aspect-video w-full place-items-center rounded-card border border-ink-800 bg-ink-950 text-center">
        <div className="space-y-2 px-6">
          <p className="text-sm font-medium text-ink-300">{t('live.offline')}</p>
          <p className="text-xs text-ink-500">{t('live.offlineHint')}</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="grid aspect-video w-full place-items-center rounded-card bg-ink-950 text-center">
        <div className="space-y-3 px-6">
          <p className="text-sm text-red-300">{t('player.error')}</p>
          <p className="text-xs text-ink-400">{error}</p>
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RotateCcw className="size-4" />
            {t('common.retry')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="relative aspect-video w-full overflow-hidden rounded-card bg-black"
    >
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        ref={videoRef}
        poster={poster || undefined}
        playsInline
        autoPlay
        muted={muted}
        className="size-full"
        onClick={togglePlay}
      />

      {buffering && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/30">
          <Spinner className="size-10" />
        </div>
      )}

      <div className="absolute left-3 top-3 flex items-center gap-2">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-white',
            atLiveEdge ? 'bg-red-600' : 'bg-ink-700',
          )}
        >
          <span className={cn('size-1.5 rounded-full bg-white',
                              atLiveEdge && 'animate-pulse')} />
          {t('live.badge')}
        </span>
        {!atLiveEdge && (
          <button
            type="button"
            onClick={seekToLive}
            className="rounded bg-black/70 px-2 py-1 text-[11px] text-white transition hover:bg-black/90"
          >
            {t('live.backToLive')}
          </button>
        )}
      </div>

      <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-gradient-to-t from-black/90 to-transparent px-3 pb-2 pt-8 text-white">
        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? t('player.pause') : t('player.play')}
          className="rounded p-1.5 transition hover:bg-white/15"
        >
          {playing ? <Pause className="size-5 fill-white" /> : <Play className="size-5 fill-white" />}
        </button>

        <div className="group/vol flex items-center">
          <button
            type="button"
            onClick={toggleMuted}
            aria-label={muted ? t('player.unmute') : t('player.mute')}
            className="rounded p-1.5 transition hover:bg-white/15"
          >
            {muted || volume === 0 ? <VolumeX className="size-5" /> : <Volume2 className="size-5" />}
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={muted ? 0 : volume}
            onChange={(event) => setVolume(Number(event.target.value))}
            aria-label={t('player.mute')}
            className="h-1 w-0 cursor-pointer accent-brand-500 opacity-0 transition-all group-hover/vol:w-20 group-hover/vol:opacity-100"
          />
        </div>

        <button
          type="button"
          onClick={toggleFullscreen}
          aria-label={fullscreen ? t('player.exitFullscreen') : t('player.fullscreen')}
          className="ml-auto rounded p-1.5 transition hover:bg-white/15"
        >
          {fullscreen ? <Minimize className="size-5" /> : <Maximize className="size-5" />}
        </button>
      </div>
    </div>
  )
}
