import { ChevronDown, ChevronUp, Film, Info } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import ShortOverlay from '@/features/shorts/ShortOverlay'
import ShortPlayer from '@/features/shorts/ShortPlayer'
import { Button, EmptyState, ErrorState, LoadingBlock } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useShortsFeed } from '@/features/shorts/api'
import { useDocumentMeta } from '@/hooks/useDocumentMeta'
import { useViewTracking } from '@/hooks/useViewTracking'

// How many clips either side of the current one get a live player.
const MOUNT_WINDOW = 1

export default function ShortsPage() {
  const { t } = useTranslation()
  const { videoId } = useParams()
  useDocumentMeta({ title: t('shorts.title'), description: t('seo.shorts') })
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const sort = searchParams.get('sort') || 'recent'

  const containerRef = useRef(null)
  const itemRefs = useRef([])
  const [index, setIndex] = useState(0)

  const { data, isLoading, isError, error, refetch } = useShortsFeed({
    sort,
    start: videoId,
  })
  const shorts = useMemo(() => data?.results ?? [], [data])
  const current = shorts[index]

  // View tracking follows whichever clip is on screen.
  const { setPlaying } = useViewTracking(current?.id, { enabled: Boolean(current) })

  useEffect(() => {
    setPlaying(Boolean(current))
    return () => setPlaying(false)
  }, [current, setPlaying])

  /* --------------------------------------------------- which clip is visible */
  useEffect(() => {
    const root = containerRef.current
    if (!root || shorts.length === 0) return undefined

    // Threshold 0.6: a clip counts as "the one you're watching" only when most
    // of it is on screen, so a slow scroll does not flip playback back and forth
    // between two neighbours.
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.6) {
            const next = Number(entry.target.dataset.index)
            if (!Number.isNaN(next)) setIndex(next)
          }
        })
      },
      { root, threshold: [0.6] },
    )

    itemRefs.current.filter(Boolean).forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [shorts.length])

  const goTo = useCallback(
    (next) => {
      const target = itemRefs.current[next]
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    },
    [],
  )

  /* -------------------------------------------------------------- keyboard */
  useEffect(() => {
    const onKey = (event) => {
      const tag = document.activeElement?.tagName
      if (['INPUT', 'TEXTAREA'].includes(tag)) return
      if (event.key === 'ArrowDown' || event.key === 'PageDown') {
        event.preventDefault()
        goTo(Math.min(index + 1, shorts.length - 1))
      } else if (event.key === 'ArrowUp' || event.key === 'PageUp') {
        event.preventDefault()
        goTo(Math.max(index - 1, 0))
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [index, shorts.length, goTo])

  // Keep the address bar on the clip being watched, so a share or a reload
  // lands on the same one — without adding a history entry per swipe.
  useEffect(() => {
    if (current) window.history.replaceState(null, '', `/shorts/${current.id}`)
  }, [current])

  if (isLoading) return <LoadingBlock />
  if (isError) return <ErrorState error={error} onRetry={refetch} />

  if (shorts.length === 0) {
    return (
      <div className="mx-auto max-w-xl py-14">
        <EmptyState
          icon={Film}
          title={t('shorts.empty')}
          description={t('shorts.emptyHint')}
        />
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center">
      <div className="mb-3 flex w-full max-w-[420px] items-center gap-2">
        <h1 className="text-lg font-bold">{t('shorts.title')}</h1>
        <select
          value={sort}
          onChange={(event) =>
            // A full navigate, not setSearchParams: the replaceState below moves
            // the address bar without telling the router, so the router's idea of
            // the location is stale. Re-entering /shorts resyncs it and starts the
            // re-sorted feed from the top, which is what changing the sort means.
            navigate(`/shorts?sort=${event.target.value}`, { replace: true })
          }
          className="sv-input ml-auto w-auto py-1.5 text-xs"
          aria-label={t('shorts.sort')}
        >
          {['recent', 'popular', 'liked', 'oldest'].map((value) => (
            <option key={value} value={value}>
              {t(`shorts.sortBy.${value}`)}
            </option>
          ))}
        </select>
      </div>

      <div className="relative">
        {/* One clip per viewport, snapped. `overscroll-contain` stops a swipe at
            the end of the feed from scrolling the page behind it. */}
        <div
          ref={containerRef}
          className="h-[calc(100dvh-11rem)] w-[min(420px,92vw)] snap-y snap-mandatory overflow-y-auto overscroll-contain rounded-card bg-black"
        >
          {shorts.map((short, position) => (
            <div
              key={short.id}
              ref={(el) => {
                itemRefs.current[position] = el
              }}
              data-index={position}
              className="relative h-full w-full snap-start snap-always"
            >
              <ShortPlayer
                short={short}
                active={position === index}
                mounted={Math.abs(position - index) <= MOUNT_WINDOW}
              />
              <ShortOverlay short={short} />
            </div>
          ))}
        </div>

        {/* Desktop affordance: a feed built for thumbs needs buttons on a mouse. */}
        <div className="absolute -right-14 top-1/2 hidden -translate-y-1/2 flex-col gap-2 lg:flex">
          <Button
            variant="secondary"
            size="icon"
            onClick={() => goTo(Math.max(index - 1, 0))}
            disabled={index === 0}
            aria-label={t('shorts.previous')}
          >
            <ChevronUp className="size-5" />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            onClick={() => goTo(Math.min(index + 1, shorts.length - 1))}
            disabled={index >= shorts.length - 1}
            aria-label={t('shorts.next')}
          >
            <ChevronDown className="size-5" />
          </Button>
        </div>
      </div>

      <p className={cn('mt-3 w-[min(420px,92vw)] text-center text-xs text-ink-500')}>
        {index + 1} / {shorts.length}
      </p>

      {/* Same honesty as the subscriptions feed: no ranking model here either. */}
      <p className="mt-2 flex w-[min(420px,92vw)] items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
        <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
        {t('shorts.rankingNote')}
      </p>
    </div>
  )
}
