import { useEffect, useRef, useState } from 'react'

import { websocketUrl } from '@/lib/api'

/**
 * Live transcoding progress for one video, over WebSocket.
 *
 * The server sends the current state immediately on connect, so a page opened
 * mid-encode shows the real percentage rather than 0. Reconnection is
 * exponential-backoff with a cap; once the pipeline reports a terminal state
 * the socket is closed deliberately and not reopened.
 */
export function useTranscodeProgress(videoId, { enabled = true, onTerminal } = {}) {
  const [progress, setProgress] = useState(null)
  const [connected, setConnected] = useState(false)
  const socketRef = useRef(null)
  const retriesRef = useRef(0)
  const timerRef = useRef(null)
  const terminalRef = useRef(false)
  const onTerminalRef = useRef(onTerminal)

  // Keep the callback current without making it a reconnect trigger.
  useEffect(() => {
    onTerminalRef.current = onTerminal
  }, [onTerminal])

  useEffect(() => {
    if (!videoId || !enabled) return undefined

    terminalRef.current = false
    let cancelled = false

    const connect = () => {
      if (cancelled || terminalRef.current) return

      const socket = new WebSocket(websocketUrl(`uploads/${videoId}/`))
      socketRef.current = socket

      socket.onopen = () => {
        retriesRef.current = 0
        setConnected(true)
      }

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type !== 'progress.update') return
          setProgress(payload)
          if (payload.terminal) {
            terminalRef.current = true
            onTerminalRef.current?.(payload)
            socket.close(1000)
          }
        } catch {
          /* ignore malformed frames */
        }
      }

      socket.onclose = (event) => {
        setConnected(false)
        // 4401/4403 are our own auth/ownership rejections — retrying is pointless.
        if (cancelled || terminalRef.current || [1000, 4401, 4403].includes(event.code)) {
          return
        }
        retriesRef.current += 1
        const delay = Math.min(1000 * 2 ** (retriesRef.current - 1), 30000)
        timerRef.current = setTimeout(connect, delay)
      }

      socket.onerror = () => socket.close()
    }

    connect()

    return () => {
      cancelled = true
      clearTimeout(timerRef.current)
      socketRef.current?.close(1000)
      socketRef.current = null
    }
  }, [videoId, enabled])

  return { progress, connected }
}
