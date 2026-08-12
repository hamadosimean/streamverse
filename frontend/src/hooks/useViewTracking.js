import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '@/lib/api'

const CLIENT_ID_KEY = 'sv.client'
const HEARTBEAT_EVERY_SECONDS = 10

/**
 * Stable, opaque per-browser id used only to deduplicate view counts.
 *
 * Not an identity: it carries no user data, is never sent anywhere except this
 * endpoint, and the server pairs it with a salted IP hash rather than storing
 * anything that could re-identify a visitor.
 */
function clientId() {
  let id = localStorage.getItem(CLIENT_ID_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(CLIENT_ID_KEY, id)
  }
  return id
}

/**
 * Count a view once the viewer has actually watched enough of it.
 *
 * Time is accumulated only while the video is *playing* — a paused tab left open
 * for an hour is not an hour of viewing. The threshold itself is enforced
 * server-side; this hook just reports honest elapsed watch time.
 */
export function useViewTracking(videoId, { enabled = true } = {}) {
  const watchedRef = useRef(0)
  const lastSentRef = useRef(0)
  const playingRef = useRef(false)
  const [state, setState] = useState(null)

  const send = useCallback(
    async (seconds) => {
      if (!videoId || seconds <= 0) return
      try {
        const { data } = await api.post(
          `/videos/${videoId}/view/`,
          { watched_seconds: Math.floor(seconds), client_id: clientId() },
          { skipAuth: false },
        )
        setState(data)
      } catch {
        // A dropped heartbeat must never surface to the viewer; the next one
        // carries the cumulative total anyway.
      }
    },
    [videoId],
  )

  // Reset when the route moves to another video.
  useEffect(() => {
    watchedRef.current = 0
    lastSentRef.current = 0
    playingRef.current = false
    setState(null)
  }, [videoId])

  useEffect(() => {
    if (!videoId || !enabled) return undefined

    const timer = setInterval(() => {
      if (!playingRef.current || document.hidden) return
      watchedRef.current += 1
      if (watchedRef.current - lastSentRef.current >= HEARTBEAT_EVERY_SECONDS) {
        lastSentRef.current = watchedRef.current
        send(watchedRef.current)
      }
    }, 1000)

    return () => {
      clearInterval(timer)
      // Flush on unmount so a viewer who navigates away just past the threshold
      // still has their view counted.
      if (watchedRef.current > lastSentRef.current) {
        send(watchedRef.current)
      }
    }
  }, [videoId, enabled, send])

  const setPlaying = useCallback((playing) => {
    playingRef.current = playing
  }, [])

  return { setPlaying, viewState: state }
}
