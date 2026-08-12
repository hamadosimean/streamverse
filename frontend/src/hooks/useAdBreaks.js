import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchAdPlan } from '@/features/monetization/api'

/**
 * Ad scheduling for one playback session.
 *
 * The *decision* — whether ads run at all, and which — is entirely server-side
 * (`POST /api/videos/<id>/ads/`). This hook only sequences what the server
 * returned: hold playback for a pre-roll, and fire a mid-roll once when the
 * playhead crosses its cue point.
 *
 * A mid-roll fires at most once per session and never on a seek backwards —
 * re-showing an ad because the viewer scrubbed is the fastest way to make
 * someone close the tab.
 */
export function useAdBreaks(videoId, { enabled = true } = {}) {
  const [plan, setPlan] = useState(null)
  const [currentAd, setCurrentAd] = useState(null)
  const playedRef = useRef(new Set())
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!videoId || !enabled) return undefined
    let cancelled = false

    playedRef.current = new Set()
    setCurrentAd(null)
    setLoaded(false)

    fetchAdPlan(videoId)
      .then((result) => {
        if (cancelled) return
        setPlan(result)
        setLoaded(true)

        const preRoll = result.breaks?.find((b) => b.placement === 'pre_roll')
        if (preRoll) {
          playedRef.current.add(preRoll.impression_id)
          setCurrentAd(preRoll)
        }
      })
      .catch(() => {
        // Playback must never depend on the ad service being reachable.
        if (!cancelled) {
          setPlan({ ads_enabled: false, breaks: [] })
          setLoaded(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [videoId, enabled])

  /** Call on timeupdate; fires a mid-roll when its cue point is crossed. */
  const onProgress = useCallback(
    (currentTime) => {
      if (!plan?.breaks?.length || currentAd) return
      const midRoll = plan.breaks.find(
        (b) =>
          b.placement === 'mid_roll' &&
          !playedRef.current.has(b.impression_id) &&
          currentTime >= b.cue_seconds,
      )
      if (midRoll) {
        playedRef.current.add(midRoll.impression_id)
        setCurrentAd(midRoll)
      }
    },
    [plan, currentAd],
  )

  const finishAd = useCallback(() => setCurrentAd(null), [])

  return {
    plan,
    currentAd,
    adsEnabled: Boolean(plan?.ads_enabled),
    isAdFree: plan?.reason === 'subscriber_ad_free',
    loaded,
    onProgress,
    finishAd,
  }
}
