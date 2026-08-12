import { Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { cn } from '@/lib/cn'

/**
 * The header search field.
 *
 * It seeds itself from `?q=` so that landing on /search — via a shared link or
 * the back button — shows the query that produced the results, instead of an
 * empty box next to a full page of hits.
 */
export default function SearchBar({ className, autoFocus = false, onSubmitted }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const inputRef = useRef(null)

  const [query, setQuery] = useState(() => searchParams.get('q') || '')

  // Re-sync on navigation, but only while on /search: elsewhere the field is a
  // draft the user may still be typing, and clobbering it would lose keystrokes.
  useEffect(() => {
    if (location.pathname === '/search') setQuery(searchParams.get('q') || '')
  }, [location.pathname, searchParams])

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus()
  }, [autoFocus])

  // "/" jumps to search, the convention on every video site. Ignored while the
  // user is typing somewhere else, otherwise it would eat the character.
  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return
      const active = document.activeElement
      if (active?.isContentEditable) return
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(active?.tagName)) return
      event.preventDefault()
      inputRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const submit = (event) => {
    event.preventDefault()
    const trimmed = query.trim()
    navigate(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/browse')
    inputRef.current?.blur()
    onSubmitted?.()
  }

  return (
    <form className={cn('relative', className)} onSubmit={submit} role="search">
      <Search
        className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-ink-400"
        aria-hidden
      />
      <input
        ref={inputRef}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => event.key === 'Escape' && inputRef.current?.blur()}
        placeholder={t('nav.search')}
        aria-label={t('nav.search')}
        className={cn(
          'h-11 w-full rounded-full border border-ink-700 bg-ink-850 pl-11 pr-24 text-sm',
          'text-ink-100 placeholder:text-ink-500',
          'transition focus:border-brand-500 focus:bg-ink-900 focus:outline-none',
          'focus:ring-2 focus:ring-brand-500/30',
          // Safari paints its own clear affordance over ours.
          '[&::-webkit-search-cancel-button]:hidden',
        )}
      />

      {query && (
        <button
          type="button"
          onClick={() => {
            setQuery('')
            inputRef.current?.focus()
          }}
          aria-label={t('nav.clearSearch')}
          className="absolute right-12 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-ink-400 transition hover:bg-ink-800 hover:text-ink-100"
        >
          <X className="size-4" />
        </button>
      )}

      <button
        type="submit"
        aria-label={t('nav.submitSearch')}
        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-full bg-brand-600 text-white transition hover:bg-brand-500"
      >
        <Search className="size-4" aria-hidden />
      </button>

      {/* Discoverability for the shortcut, without stealing room from the field. */}
      <kbd className="pointer-events-none absolute -bottom-6 right-2 hidden text-[10px] text-ink-600 xl:block">
        {t('nav.searchHint')}
      </kbd>
    </form>
  )
}
