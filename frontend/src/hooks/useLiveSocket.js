import { useCallback, useEffect, useRef, useState } from 'react'

import { websocketUrl } from '@/lib/api'

const MAX_MESSAGES = 200

/**
 * One socket per live channel, carrying chat, the viewer count and status
 * changes.
 *
 * Anonymous viewers connect too — they are part of the audience and should see
 * the count and the conversation. The server decides whether they may post;
 * `canChat` here is only what the UI uses to disable the input.
 */
export function useLiveSocket(slug, { enabled = true } = {}) {
  const [messages, setMessages] = useState([])
  const [viewerCount, setViewerCount] = useState(0)
  const [status, setStatus] = useState(null)
  const [canChat, setCanChat] = useState(false)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)

  const socketRef = useRef(null)
  const retriesRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!slug || !enabled) return undefined
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      const socket = new WebSocket(websocketUrl(`live/${slug}/`))
      socketRef.current = socket

      socket.onopen = () => {
        retriesRef.current = 0
        setConnected(true)
        setError(null)
      }

      socket.onmessage = (event) => {
        let frame
        try {
          frame = JSON.parse(event.data)
        } catch {
          return
        }

        switch (frame.type) {
          case 'live.hello':
            setStatus(frame.status)
            setCanChat(Boolean(frame.can_chat && frame.chat_enabled))
            setViewerCount(frame.viewer_count ?? 0)
            setMessages(frame.messages ?? [])
            break
          case 'chat.message':
            // Bounded: a busy stream would otherwise grow this array without
            // limit for as long as the tab stays open.
            setMessages((current) =>
              [...current, frame].slice(-MAX_MESSAGES),
            )
            break
          case 'live.viewers':
            setViewerCount(frame.count ?? 0)
            break
          case 'live.status':
            setStatus(frame.status)
            break
          case 'live.error':
            setError(frame.detail || frame.code)
            break
          default:
            break
        }
      }

      socket.onclose = (closeEvent) => {
        setConnected(false)
        // 4404 = no such channel; retrying would just loop.
        if (cancelled || [1000, 4404].includes(closeEvent.code)) return
        retriesRef.current += 1
        const delay = Math.min(1000 * 2 ** (retriesRef.current - 1), 20000)
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
  }, [slug, enabled])

  const sendMessage = useCallback((content) => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    socket.send(JSON.stringify({ type: 'chat.send', content }))
    return true
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return { messages, viewerCount, status, canChat, connected, error,
           sendMessage, clearError }
}
