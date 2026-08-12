import Hls from 'hls.js'
import { Pause, Play, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/cn'
import { usePlayerStore } from '@/stores/usePlayerStore'

/**
 * One Short in the vertical feed.
 *
 * Three constraints drive the whole design:
 *
 * 1. **Only the visible clip may play.** Otherwise a scroll leaves several
 *    videos running and their audio overlapping.
 * 2. **hls.js is only attached when the clip is near the viewport.** A feed of
 *    twenty Shorts each holding a live MSE instance would buffer twenty streams
 *    at once — hundreds of MB and a stalled scroll on a phone. `mounted` is the
 *    window (current ± 1); everything outside it renders a poster only.
 * 3. **Autoplay must start muted.** Browsers block unmuted autoplay outright, so
 *    an unmuted first play would silently never start. The feed begins muted
 *    with a visible control, and the choice is remembered once the user makes it.
 */
export default function ShortPlayer({ short, active, mounted, onProgress, onEnded }) {
  const { t } = useTranslation()
  const videoRef = useRef(null)
  const hlsRef = useRef(null)

  const { muted, toggleMuted, setMuted } = usePlayerStore()
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)
  const [progress, setProgress] = useState(0)

  /* ---------------------------------------------------------- attach HLS */
  useEffect(() => {
    const video = videoRef.current
    if (!video || !mounted || !short.playback_url) return undefined

    setReady(false)

    if (!Hls.isSupported()) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = short.playback_url
        setReady(true)
        return () => {
          video.removeAttribute('src')
          video.load()
        }
      }
      return undefined
    }

    const hls = new Hls({
      // A Short is seconds long — buffer it whole and stop, rather than running
      // the ABR ladder over a clip that ends before it could switch usefully.
      maxBufferLength: 30,
      capLevelToPlayerSize: true,
      startLevel: -1,
      enableWorker: true,
      lowLatencyMode: false,
    })
    hlsRef.current = hls
    hls.on(Hls.Events.MANIFEST_PARSED, () => setReady(true))
    hls.on(Hls.Events.ERROR, (_e, data) => {
      if (!data.fatal) return
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad()
      else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError()
      else hls.destroy()
    })
    hls.loadSource(short.playback_url)
    hls.attachMedia(video)

    return () => {
      hls.destroy()
      hlsRef.current = null
    }
  }, [mounted, short.playback_url])

  /* --------------------------------------------------- play only when active */
  useEffect(() => {
    const video = videoRef.current
    if (!video || !mounted) return

    if (active) {
      video.muted = muted
      video.play().then(() => setPlaying(true)).catch(() => {
        // Autoplay refused (almost always the unmuted case). Fall back to muted
        // rather than showing a frozen frame, and tell the store, so the toggle
        // reflects the element instead of lying about it.
        video.muted = true
        setMuted(true)
        video.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
      })
    } else {
      video.pause()
      // Rewind so returning to a clip starts it over, which is what a looping
      // feed implies.
      video.currentTime = 0
      setPlaying(false)
      setProgress(0)
    }
  }, [active, mounted, ready, muted, setMuted])

  useEffect(() => {
    const video = videoRef.current
    if (video) video.muted = muted
  }, [muted])

  /* ------------------------------------------------------------- events */
  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined

    const onTime = () => {
      if (video.duration) setProgress((video.currentTime / video.duration) * 100)
      if (active) onProgress?.(video.currentTime)
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onEnd = () => onEnded?.()

    video.addEventListener('timeupdate', onTime)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('ended', onEnd)
    return () => {
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('ended', onEnd)
    }
  }, [active, onProgress, onEnded])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) video.play().catch(() => {})
    else video.pause()
  }, [])

  return (
    <div className="relative size-full bg-black">
      {mounted ? (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <video
          ref={videoRef}
          poster={short.poster_url || undefined}
          playsInline
          loop
          muted={muted}
          preload={active ? 'auto' : 'metadata'}
          onClick={togglePlay}
          className="size-full object-contain"
        />
      ) : (
        // Out of window: a poster, so scrolling stays smooth and no stream loads.
        <div
          className="size-full bg-cover bg-center opacity-70"
          style={short.poster_url ? { backgroundImage: `url(${short.poster_url})` } : undefined}
        />
      )}

      {/* Tap target for play/pause, behind the action rail. */}
      {mounted && (
        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? t('player.pause') : t('player.play')}
          className="absolute inset-0 z-10 grid place-items-center"
        >
          {!playing && ready && (
            <span className="grid size-16 place-items-center rounded-full bg-black/50">
              <Play className="size-8 translate-x-0.5 fill-white text-white" aria-hidden />
            </span>
          )}
          {playing && (
            <Pause className="size-8 fill-white text-white opacity-0" aria-hidden />
          )}
        </button>
      )}

      {/* Mute toggle — the feed starts muted because browsers require it. */}
      {active && (
        <button
          type="button"
          onClick={toggleMuted}
          aria-label={muted ? t('player.unmute') : t('player.mute')}
          className="absolute right-3 top-3 z-20 rounded-full bg-black/60 p-2.5 text-white transition hover:bg-black/80"
        >
          {muted ? <VolumeX className="size-5" /> : <Volume2 className="size-5" />}
        </button>
      )}

      <div className="absolute inset-x-0 bottom-0 z-20 h-0.5 bg-white/20">
        <div
          className={cn('h-full bg-white transition-[width] duration-200')}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}
