import {
  Camera,
  CameraOff,
  Mic,
  MicOff,
  MonitorUp,
  RadioTower,
  RefreshCw,
  Square,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import { Badge, Button, Field } from '@/components/ui'
import { api, apiErrorMessage } from '@/lib/api'
import { formatDuration } from '@/lib/format'
import { publish, WhipError } from '@/features/live/whip'

const CAMERA_CONSTRAINTS = {
  // 720p30 is the sweet spot for a phone: it encodes in hardware on anything
  // recent, and the bridge copies the track through untouched, so whatever the
  // camera produces is exactly what viewers get.
  width: { ideal: 1280 },
  height: { ideal: 720 },
  frameRate: { ideal: 30 },
}

/** Turn a getUserMedia rejection into something a person can act on. */
function mediaErrorKey(error) {
  switch (error?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'live.broadcast.errorDenied'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'live.broadcast.errorNoDevice'
    case 'NotReadableError':
      return 'live.broadcast.errorBusyDevice'
    default:
      return 'live.broadcast.errorDevice'
  }
}

function whipErrorKey(error) {
  if (!(error instanceof WhipError)) return 'live.broadcast.errorConnect'
  return {
    no_h264: 'live.broadcast.errorNoH264',
    unsupported: 'live.broadcast.errorUnsupported',
    busy: 'live.broadcast.errorBusy',
    rejected: 'live.broadcast.errorRejected',
  }[error.code] ?? 'live.broadcast.errorConnect'
}

/**
 * Broadcast straight from this device — no OBS, no stream key.
 *
 * The panel owns exactly one MediaStream at a time. Switching source (camera →
 * screen, front → back) while live is deliberately not supported: it would mean
 * renegotiating the WHIP session mid-broadcast, and a dropped renegotiation
 * ends the stream rather than degrading it.
 */
export default function GoLivePanel({ channel, onStatusChange }) {
  const { t } = useTranslation()

  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const sessionRef = useRef(null)
  const startedAtRef = useRef(null)

  const [phase, setPhase] = useState('idle') // idle | preview | connecting | live
  const [source, setSource] = useState('camera') // camera | screen
  const [facing, setFacing] = useState('user') // user | environment
  const [micOn, setMicOn] = useState(true)
  const [camOn, setCamOn] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null)

  // getUserMedia exists only in a secure context. On a phone that means the
  // stack must be reached over HTTPS or through localhost — an http:// LAN
  // address silently has no camera at all, which is worth saying plainly
  // rather than letting the user think their device is broken.
  const secure = typeof window !== 'undefined' && window.isSecureContext

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  // Leaving the page mid-broadcast must end the broadcast, not orphan it.
  useEffect(() => () => {
    sessionRef.current?.stop()
    sessionRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  useEffect(() => {
    if (phase !== 'live') return undefined
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [phase])

  const attach = (stream) => {
    streamRef.current = stream
    if (videoRef.current) {
      videoRef.current.srcObject = stream
      videoRef.current.play?.().catch(() => {})
    }
    setMicOn(stream.getAudioTracks().some((track) => track.enabled))
    setCamOn(stream.getVideoTracks().some((track) => track.enabled))
  }

  const openPreview = async (nextSource = source, nextFacing = facing) => {
    setError(null)
    stopStream()
    try {
      const stream = nextSource === 'screen'
        ? await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true })
        : await navigator.mediaDevices.getUserMedia({
            video: { ...CAMERA_CONSTRAINTS, facingMode: nextFacing },
            audio: { echoCancellation: true, noiseSuppression: true },
          })
      attach(stream)
      setSource(nextSource)
      setFacing(nextFacing)
      setPhase('preview')
    } catch (mediaError) {
      setError(t(mediaErrorKey(mediaError)))
      setPhase('idle')
    }
  }

  const goLive = async () => {
    if (!streamRef.current) return
    setError(null)
    setPhase('connecting')

    try {
      // The ticket is minted per broadcast and expires in minutes, so it is
      // fetched here rather than held by the page.
      const { data } = await api.post('/live/me/webrtc-ticket/')
      sessionRef.current = await publish({
        url: data.publish_url,
        stream: streamRef.current,
        onStateChange: (state) => {
          if (state === 'failed' || state === 'closed') {
            setError(t('live.broadcast.errorDropped'))
            setPhase('preview')
            sessionRef.current = null
            onStatusChange?.()
          }
        },
      })
      startedAtRef.current = Date.now()
      setElapsed(0)
      setPhase('live')
      toast.success(t('live.broadcast.started'))
      // The channel flips to `live` only once the bridge's output reaches the
      // ingest path, a second or two later — so refresh rather than assume.
      setTimeout(() => onStatusChange?.(), 3000)
    } catch (publishError) {
      setPhase('preview')
      setError(
        publishError instanceof WhipError
          ? t(whipErrorKey(publishError))
          : apiErrorMessage(publishError, t('live.broadcast.errorConnect')),
      )
    }
  }

  const stopLive = async () => {
    await sessionRef.current?.stop()
    sessionRef.current = null
    setPhase('preview')
    toast.success(t('live.broadcast.stopped'))
    onStatusChange?.()
  }

  const toggleTrack = (kind) => {
    const tracks = kind === 'audio'
      ? streamRef.current?.getAudioTracks()
      : streamRef.current?.getVideoTracks()
    if (!tracks?.length) return
    const enabled = !tracks[0].enabled
    tracks.forEach((track) => { track.enabled = enabled })
    if (kind === 'audio') setMicOn(enabled)
    else setCamOn(enabled)
  }

  const busy = phase === 'connecting'
  const live = phase === 'live'

  return (
    <section className="sv-card mb-5 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <RadioTower className="size-4 text-red-400" aria-hidden />
          {t('live.broadcast.title')}
        </h2>
        {live && (
          <div className="flex items-center gap-2">
            <Badge tone="danger">{t('live.badge')}</Badge>
            <span className="font-mono text-xs text-ink-300">{formatDuration(elapsed)}</span>
          </div>
        )}
      </div>

      <p className="mb-4 text-xs text-ink-400">{t('live.broadcast.hint')}</p>

      {!secure && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {t('live.broadcast.insecureContext')}
        </p>
      )}

      <div className="relative mb-4 overflow-hidden rounded-card border border-ink-800 bg-ink-950">
        <video
          ref={videoRef}
          muted
          playsInline
          autoPlay
          className="aspect-video w-full bg-ink-950 object-contain"
        />

        {phase === 'idle' && (
          <div className="absolute inset-0 grid place-items-center bg-ink-950/80 p-4 text-center">
            <div>
              <Camera className="mx-auto mb-2 size-8 text-ink-600" aria-hidden />
              <p className="text-xs text-ink-400">{t('live.broadcast.previewEmpty')}</p>
            </div>
          </div>
        )}

        {live && (
          <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-red-600 px-2.5 py-1 text-xs font-bold text-white">
            <span className="size-1.5 animate-pulse rounded-full bg-white" />
            {t('live.badge')}
          </span>
        )}
      </div>

      {error && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-200">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      )}

      {/* Source picker. Disabled while live: switching would mean renegotiating
          the session, and a failed renegotiation drops the broadcast. */}
      <Field label={t('live.broadcast.source')}>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant={source === 'camera' ? 'primary' : 'secondary'}
            size="sm"
            disabled={live || busy || !secure}
            onClick={() => openPreview('camera', facing)}
          >
            <Camera className="size-4" aria-hidden />
            {t('live.broadcast.sourceCamera')}
          </Button>

          <Button
            type="button"
            variant={source === 'screen' ? 'primary' : 'secondary'}
            size="sm"
            disabled={live || busy || !secure}
            onClick={() => openPreview('screen', facing)}
          >
            <MonitorUp className="size-4" aria-hidden />
            {t('live.broadcast.sourceScreen')}
          </Button>

          {source === 'camera' && phase !== 'idle' && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={live || busy}
              onClick={() => openPreview('camera', facing === 'user' ? 'environment' : 'user')}
            >
              <RefreshCw className="size-4" aria-hidden />
              {t('live.broadcast.flipCamera')}
            </Button>
          )}
        </div>
      </Field>

      <div className="flex flex-wrap items-center gap-2">
        {phase === 'idle' ? (
          <Button onClick={() => openPreview()} disabled={!secure}>
            <Camera className="size-4" aria-hidden />
            {t('live.broadcast.enable')}
          </Button>
        ) : live ? (
          <Button variant="danger" onClick={stopLive}>
            <Square className="size-4" aria-hidden />
            {t('live.broadcast.stop')}
          </Button>
        ) : (
          <Button onClick={goLive} loading={busy}>
            <RadioTower className="size-4" aria-hidden />
            {t('live.broadcast.start')}
          </Button>
        )}

        {phase !== 'idle' && (
          <>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => toggleTrack('audio')}
              aria-label={micOn ? t('live.broadcast.muteMic') : t('live.broadcast.unmuteMic')}
              aria-pressed={!micOn}
            >
              {micOn ? <Mic className="size-4" /> : <MicOff className="size-4 text-red-400" />}
            </Button>

            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => toggleTrack('video')}
              aria-label={camOn ? t('live.broadcast.hideCamera') : t('live.broadcast.showCamera')}
              aria-pressed={!camOn}
            >
              {camOn ? <Camera className="size-4" /> : <CameraOff className="size-4 text-red-400" />}
            </Button>
          </>
        )}

        {live && (
          <span className="text-xs text-ink-500">
            {t('live.broadcast.liveHint', { slug: channel.slug })}
          </span>
        )}
      </div>
    </section>
  )
}
