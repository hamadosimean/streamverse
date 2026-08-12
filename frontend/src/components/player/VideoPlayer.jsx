import Hls from 'hls.js'
import {
  Maximize,
  Minimize,
  Pause,
  PictureInPicture2,
  Play,
  RotateCcw,
  Settings,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDuration } from '@/lib/format'
import { usePlayerStore } from '@/stores/usePlayerStore'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]
const SEEK_STEP = 5

/**
 * Adaptive-bitrate player.
 *
 * hls.js drives playback everywhere it is supported; Safari (desktop and iOS)
 * gets the native HLS path instead, because it plays `.m3u8` in the `<video>`
 * element directly and hls.js is not supported on iOS at all.
 *
 * The controls are custom rather than `controls`-attribute native, because the
 * scrubbing-preview thumbnails and the manual rendition selector have no native
 * equivalent.
 */
export default function VideoPlayer({
  source,
  title,
  onPlayingChange,
  onProgress,
  adOverlay = null,
  adPlaying = false,
}) {
  const { t } = useTranslation()
  const containerRef = useRef(null)
  const videoRef = useRef(null)
  const hlsRef = useRef(null)
  const hideTimerRef = useRef(null)

  const { volume, muted, preferredLevel, setVolume, toggleMuted, setPreferredLevel } =
    usePlayerStore()

  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [buffering, setBuffering] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(source?.duration_seconds || 0)
  const [buffered, setBuffered] = useState(0)
  const [levels, setLevels] = useState([])
  const [activeLevel, setActiveLevel] = useState(-1)
  const [speed, setSpeed] = useState(1)
  const [fullscreen, setFullscreen] = useState(false)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [error, setError] = useState(null)
  const [hover, setHover] = useState(null) // { time, x } for the seek preview

  const spriteMeta = source?.sprite_meta
  const spriteUrl = source?.sprite_url

  /* ------------------------------------------------------------ attach HLS */
  useEffect(() => {
    const video = videoRef.current
    if (!video || !source?.master_url) return undefined

    setError(null)
    setReady(false)

    // Safari plays HLS natively and hls.js is unsupported on iOS — use the
    // native path there rather than shipping a broken MSE fallback.
    if (!Hls.isSupported()) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = source.master_url
        setReady(true)
        return () => {
          video.removeAttribute('src')
          video.load()
        }
      }
      setError(t('player.notSupported'))
      return undefined
    }

    const hls = new Hls({
      // Keep the forward buffer modest: a 30-minute video at 5 Mbps would
      // otherwise happily download hundreds of MB the viewer never watches.
      maxBufferLength: 30,
      maxMaxBufferLength: 120,
      backBufferLength: 30,
      enableWorker: true,
      lowLatencyMode: false,
      // Manifests for private videos carry presigned URLs and are Django-served;
      // a stale cached copy would hand us expired segment links.
      startLevel: -1,
    })
    hlsRef.current = hls

    hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
      setLevels(data.levels || [])
      // Restore the viewer's manual quality choice if it still exists.
      if (preferredLevel >= 0 && preferredLevel < (data.levels?.length || 0)) {
        hls.currentLevel = preferredLevel
      }
      setReady(true)
    })

    hls.on(Hls.Events.LEVEL_SWITCHED, (_event, data) => setActiveLevel(data.level))

    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return
      switch (data.type) {
        case Hls.ErrorTypes.NETWORK_ERROR:
          // Usually a transient segment fetch failure — retry rather than give up.
          hls.startLoad()
          break
        case Hls.ErrorTypes.MEDIA_ERROR:
          hls.recoverMediaError()
          break
        default:
          setError(t('player.errorHint'))
          hls.destroy()
      }
    })

    hls.loadSource(source.master_url)
    hls.attachMedia(video)

    return () => {
      hls.destroy()
      hlsRef.current = null
    }
    // `preferredLevel` is read once at manifest time on purpose; changing it
    // later is handled by the selector below, not by rebuilding the player.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.master_url, t])

  /* --------------------------------------------------- video element wiring */
  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined

    video.volume = volume
    video.muted = muted

    const onTimeUpdate = () => {
      setCurrentTime(video.currentTime)
      if (video.buffered.length > 0) {
        setBuffered(video.buffered.end(video.buffered.length - 1))
      }
      // Drives mid-roll cue points; the decision of *whether* to fire one is
      // the server's, this only reports the playhead.
      onProgress?.(video.currentTime)
    }
    const onLoaded = () => setDuration(video.duration || source?.duration_seconds || 0)
    // View tracking needs to know when the video is genuinely playing, so a
    // paused tab left open never accumulates watch time.
    const onPlay = () => {
      setPlaying(true)
      onPlayingChange?.(true)
    }
    const onPause = () => {
      setPlaying(false)
      onPlayingChange?.(false)
    }
    const onWaiting = () => setBuffering(true)
    const onPlaying = () => setBuffering(false)
    const onEnded = () => {
      setPlaying(false)
      onPlayingChange?.(false)
    }

    video.addEventListener('timeupdate', onTimeUpdate)
    video.addEventListener('loadedmetadata', onLoaded)
    video.addEventListener('durationchange', onLoaded)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('waiting', onWaiting)
    video.addEventListener('playing', onPlaying)
    video.addEventListener('ended', onEnded)

    return () => {
      video.removeEventListener('timeupdate', onTimeUpdate)
      video.removeEventListener('loadedmetadata', onLoaded)
      video.removeEventListener('durationchange', onLoaded)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('waiting', onWaiting)
      video.removeEventListener('playing', onPlaying)
      video.removeEventListener('ended', onEnded)
    }
  }, [volume, muted, source?.duration_seconds, onPlayingChange, onProgress])

  // An ad break pauses the content underneath it and resumes when it ends —
  // otherwise the video would play on unseen behind the overlay.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (adPlaying) {
      video.pause()
    } else if (ready && playing) {
      video.play().catch(() => {})
    }
    // `playing` is intentionally not a dependency: reacting to it here would
    // fight the user's own pause.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adPlaying, ready])

  useEffect(() => {
    const onFullscreenChange = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [])

  /* ------------------------------------------------------------- behaviours */
  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) video.play().catch(() => setError(t('player.errorHint')))
    else video.pause()
  }, [t])

  const seekTo = useCallback((time) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, Math.min(time, video.duration || 0))
  }, [])

  const seekBy = useCallback(
    (delta) => seekTo((videoRef.current?.currentTime || 0) + delta),
    [seekTo],
  )

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen()
    else containerRef.current?.requestFullscreen?.()
  }, [])

  const togglePip = useCallback(async () => {
    const video = videoRef.current
    if (!video || !document.pictureInPictureEnabled) return
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture()
      else await video.requestPictureInPicture()
    } catch {
      /* user gesture requirements vary by browser; failing silently is correct here */
    }
  }, [])

  const selectLevel = useCallback(
    (level) => {
      setPreferredLevel(level)
      if (hlsRef.current) hlsRef.current.currentLevel = level
      setSettingsOpen(false)
    },
    [setPreferredLevel],
  )

  const changeSpeed = useCallback((value) => {
    setSpeed(value)
    if (videoRef.current) videoRef.current.playbackRate = value
    setSettingsOpen(false)
  }, [])

  /* ----------------------------------------------------- keyboard shortcuts */
  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = document.activeElement?.tagName
      // Never hijack typing in a form field.
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return
      if (!containerRef.current?.contains(document.activeElement) && !fullscreen) {
        // Only claim the keyboard when the player is focused or fullscreen.
        if (document.activeElement !== document.body) return
      }

      switch (event.key) {
        case ' ':
        case 'k':
          event.preventDefault()
          togglePlay()
          break
        case 'ArrowRight':
          event.preventDefault()
          seekBy(SEEK_STEP)
          break
        case 'ArrowLeft':
          event.preventDefault()
          seekBy(-SEEK_STEP)
          break
        case 'm':
          toggleMuted()
          break
        case 'f':
          toggleFullscreen()
          break
        default:
          break
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [togglePlay, seekBy, toggleMuted, toggleFullscreen, fullscreen])

  /* ------------------------------------------------- auto-hide the controls */
  const showControls = useCallback(() => {
    setControlsVisible(true)
    clearTimeout(hideTimerRef.current)
    hideTimerRef.current = setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused && !settingsOpen) {
        setControlsVisible(false)
      }
    }, 2800)
  }, [settingsOpen])

  useEffect(() => () => clearTimeout(hideTimerRef.current), [])

  /* ------------------------------------------------------ seek-bar previews */
  const spriteTile = useMemo(() => {
    if (!spriteMeta || !spriteUrl || hover == null) return null
    const { tiles, interval, columns, tile_width: tw, tile_height: th } = spriteMeta
    const index = Math.max(0, Math.min(Math.floor(hover.time / interval), tiles - 1))
    return {
      width: tw,
      height: th,
      backgroundImage: `url(${spriteUrl})`,
      backgroundPosition: `-${(index % columns) * tw}px -${Math.floor(index / columns) * th}px`,
    }
  }, [spriteMeta, spriteUrl, hover])

  const onSeekBarMove = (event) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1))
    setHover({ time: ratio * duration, x: ratio * rect.width })
  }

  const onSeekBarClick = (event) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1))
    seekTo(ratio * duration)
  }

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0
  const bufferedPercent = duration > 0 ? (buffered / duration) * 100 : 0

  /* ------------------------------------------------------------------ error */
  if (error) {
    return (
      <div className="grid aspect-video w-full place-items-center rounded-card bg-ink-950 text-center">
        <div className="space-y-3 px-6">
          <p className="text-sm font-medium text-red-300">{t('player.error')}</p>
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
      tabIndex={-1}
      className="group relative aspect-video w-full overflow-hidden rounded-card bg-black"
      onMouseMove={showControls}
      onMouseLeave={() => playing && setControlsVisible(false)}
    >
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        ref={videoRef}
        poster={source?.poster_url || undefined}
        playsInline
        className="size-full"
        onClick={togglePlay}
        title={title}
      />

      {adOverlay}

      {(!ready || buffering) && !adPlaying && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/30">
          <Spinner className="size-10" />
        </div>
      )}

      {!playing && ready && !adPlaying && (
        <button
          type="button"
          onClick={togglePlay}
          aria-label={t('player.play')}
          className="absolute inset-0 grid place-items-center bg-black/20 transition hover:bg-black/30"
        >
          <span className="grid size-16 place-items-center rounded-full bg-brand-600/90 shadow-lg">
            <Play className="size-7 translate-x-0.5 fill-white text-white" aria-hidden />
          </span>
        </button>
      )}

      <div
        className={cn(
          'absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/60 to-transparent px-3 pb-2 pt-8 transition-opacity',
          controlsVisible || !playing ? 'opacity-100' : 'opacity-0',
          // The ad has its own controls; showing both would let a viewer seek
          // past an ad using the content's seek bar.
          adPlaying && 'pointer-events-none opacity-0',
        )}
      >
        {/* ------------------------------------------------------- seek bar */}
        <div
          className="group/seek relative mb-2 cursor-pointer py-2"
          onMouseMove={onSeekBarMove}
          onMouseLeave={() => setHover(null)}
          onClick={onSeekBarClick}
          role="slider"
          aria-label={t('player.play')}
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(currentTime)}
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'ArrowRight') seekBy(SEEK_STEP)
            if (event.key === 'ArrowLeft') seekBy(-SEEK_STEP)
          }}
        >
          <div className="h-1 w-full overflow-hidden rounded-full bg-white/25 transition-all group-hover/seek:h-1.5">
            <div
              className="absolute h-1 rounded-full bg-white/35 transition-all group-hover/seek:h-1.5"
              style={{ width: `${bufferedPercent}%` }}
            />
            <div
              className="absolute h-1 rounded-full bg-brand-500 transition-all group-hover/seek:h-1.5"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          {hover && (
            <div
              className="pointer-events-none absolute bottom-6 z-10 -translate-x-1/2"
              style={{ left: `${hover.x}px` }}
            >
              {spriteTile && (
                <div
                  className="rounded border-2 border-white/80 bg-ink-950 bg-no-repeat shadow-lg"
                  style={{
                    width: `${spriteTile.width}px`,
                    height: `${spriteTile.height}px`,
                    backgroundImage: spriteTile.backgroundImage,
                    backgroundPosition: spriteTile.backgroundPosition,
                  }}
                />
              )}
              <p className="mt-1 text-center text-[11px] font-medium tabular-nums text-white drop-shadow">
                {formatDuration(hover.time)}
              </p>
            </div>
          )}
        </div>

        {/* -------------------------------------------------------- controls */}
        <div className="flex items-center gap-1 text-white">
          <button
            type="button"
            onClick={togglePlay}
            aria-label={playing ? t('player.pause') : t('player.play')}
            className="rounded p-1.5 transition hover:bg-white/15"
          >
            {playing ? (
              <Pause className="size-5 fill-white" />
            ) : (
              <Play className="size-5 fill-white" />
            )}
          </button>

          <div className="group/vol flex items-center">
            <button
              type="button"
              onClick={toggleMuted}
              aria-label={muted ? t('player.unmute') : t('player.mute')}
              className="rounded p-1.5 transition hover:bg-white/15"
            >
              {muted || volume === 0 ? (
                <VolumeX className="size-5" />
              ) : (
                <Volume2 className="size-5" />
              )}
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

          <span className="ml-1 text-xs tabular-nums text-white/90">
            {formatDuration(currentTime)} / {formatDuration(duration)}
          </span>

          <div className="ml-auto flex items-center gap-1">
            <div className="relative">
              <button
                type="button"
                onClick={() => setSettingsOpen((open) => !open)}
                aria-label={t('player.settings')}
                aria-expanded={settingsOpen}
                className="rounded p-1.5 transition hover:bg-white/15"
              >
                <Settings className="size-5" />
              </button>

              {settingsOpen && (
                <div className="absolute bottom-11 right-0 w-52 rounded-lg border border-ink-700 bg-ink-850/98 p-2 text-xs shadow-2xl backdrop-blur">
                  <p className="px-2 py-1 font-semibold text-ink-300">
                    {t('watch.quality')}
                  </p>
                  <button
                    type="button"
                    onClick={() => selectLevel(-1)}
                    className={cn(
                      'flex w-full items-center justify-between rounded px-2 py-1.5 transition hover:bg-ink-700',
                      preferredLevel === -1 && 'text-brand-300',
                    )}
                  >
                    {t('watch.auto')}
                    {preferredLevel === -1 && activeLevel >= 0 && levels[activeLevel] && (
                      <span className="text-ink-400">{levels[activeLevel].height}p</span>
                    )}
                  </button>
                  {levels.map((level, index) => (
                    <button
                      key={`${level.height}-${index}`}
                      type="button"
                      onClick={() => selectLevel(index)}
                      className={cn(
                        'flex w-full items-center justify-between rounded px-2 py-1.5 transition hover:bg-ink-700',
                        preferredLevel === index && 'text-brand-300',
                      )}
                    >
                      <span>{level.height}p</span>
                      <span className="text-ink-400">
                        {Math.round(level.bitrate / 1000)} kbps
                      </span>
                    </button>
                  ))}

                  <p className="mt-2 border-t border-ink-700 px-2 pb-1 pt-2 font-semibold text-ink-300">
                    {t('player.speed')}
                  </p>
                  <div className="flex flex-wrap gap-1 px-1">
                    {SPEEDS.map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => changeSpeed(value)}
                        className={cn(
                          'rounded px-2 py-1 transition hover:bg-ink-700',
                          speed === value && 'bg-brand-600 text-white',
                        )}
                      >
                        {value === 1 ? t('player.normal') : `${value}x`}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {document.pictureInPictureEnabled && (
              <button
                type="button"
                onClick={togglePip}
                aria-label={t('player.pictureInPicture')}
                className="rounded p-1.5 transition hover:bg-white/15"
              >
                <PictureInPicture2 className="size-5" />
              </button>
            )}

            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label={fullscreen ? t('player.exitFullscreen') : t('player.fullscreen')}
              className="rounded p-1.5 transition hover:bg-white/15"
            >
              {fullscreen ? <Minimize className="size-5" /> : <Maximize className="size-5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
