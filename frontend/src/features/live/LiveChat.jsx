import { MessageSquare, Send, WifiOff } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useAuthStore } from '@/stores/useAuthStore'

/**
 * Live chat pane.
 *
 * Autoscroll is *conditional*: it only follows new messages when the reader is
 * already at the bottom. Yanking someone back down while they are reading
 * earlier messages is the classic live-chat annoyance.
 */
export default function LiveChat({ slug, socket, chatEnabled = true }) {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)
  const listRef = useRef(null)
  const pinnedRef = useRef(true)
  const [draft, setDraft] = useState('')

  const { messages, canChat, connected, error, sendMessage, clearError } = socket

  useEffect(() => {
    const list = listRef.current
    if (list && pinnedRef.current) {
      list.scrollTop = list.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    if (!error) return undefined
    const timer = setTimeout(clearError, 4000)
    return () => clearTimeout(timer)
  }, [error, clearError])

  const onScroll = () => {
    const list = listRef.current
    if (!list) return
    pinnedRef.current =
      list.scrollHeight - list.scrollTop - list.clientHeight < 40
  }

  const submit = (event) => {
    event.preventDefault()
    const text = draft.trim()
    if (!text) return
    if (sendMessage(text)) setDraft('')
  }

  return (
    <div className="flex h-[520px] flex-col rounded-card border border-ink-800 bg-ink-850 lg:h-[calc(100vh-11rem)]">
      <header className="flex items-center gap-2 border-b border-ink-800 px-4 py-3">
        <MessageSquare className="size-4 text-brand-400" aria-hidden />
        <h2 className="text-sm font-semibold">{t('live.chat')}</h2>
        <span
          className={cn(
            'ml-auto inline-flex items-center gap-1.5 text-[11px]',
            connected ? 'text-emerald-400' : 'text-ink-500',
          )}
        >
          {connected ? (
            <>
              <span className="size-1.5 rounded-full bg-emerald-400" />
              {t('live.connected')}
            </>
          ) : (
            <>
              <WifiOff className="size-3" aria-hidden />
              {t('live.reconnecting')}
            </>
          )}
        </span>
      </header>

      <div
        ref={listRef}
        onScroll={onScroll}
        className="flex-1 space-y-2 overflow-y-auto px-4 py-3"
      >
        {messages.length === 0 && (
          <p className="py-8 text-center text-xs text-ink-500">
            {t('live.chatEmpty')}
          </p>
        )}
        {messages.map((message) => (
          <p key={message.id ?? `${message.username}-${message.created_at}`}
             className="text-sm leading-snug">
            <Link
              to={`/c/${message.username}`}
              className="font-semibold text-brand-300 hover:underline"
            >
              {message.user}
            </Link>
            <span className="text-ink-500">: </span>
            <span className="break-words text-ink-200">{message.content}</span>
          </p>
        ))}
      </div>

      {error && (
        <p className="border-t border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-300">
          {error}
        </p>
      )}

      <form onSubmit={submit} className="border-t border-ink-800 p-3">
        {!chatEnabled ? (
          <p className="text-center text-xs text-ink-500">{t('live.chatDisabled')}</p>
        ) : !user ? (
          <p className="text-center text-xs text-ink-400">
            <Link to="/login" className="text-brand-300 hover:underline">
              {t('nav.login')}
            </Link>{' '}
            {t('live.loginToChat')}
          </p>
        ) : (
          <div className="flex gap-2">
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={500}
              disabled={!canChat || !connected}
              placeholder={
                canChat ? t('live.chatPlaceholder') : t('live.chatClosed')
              }
              className="sv-input"
              aria-label={t('live.chat')}
            />
            <Button
              type="submit"
              size="icon"
              disabled={!draft.trim() || !canChat || !connected}
              aria-label={t('live.send')}
            >
              <Send className="size-4" />
            </Button>
          </div>
        )}
      </form>
    </div>
  )
}
