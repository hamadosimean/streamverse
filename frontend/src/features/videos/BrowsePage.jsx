import { Info, SearchX } from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { VideoGrid } from '@/components/VideoCard'
import { Button, EmptyState, ErrorState, SkeletonGrid } from '@/components/ui'
import { cn } from '@/lib/cn'
import { categoryLabel } from '@/lib/i18n'
import { useCategories, useVideoList } from '@/features/videos/api'

const SORTS = [
  { value: 'recent', labelKey: 'browse.sortRecent' },
  { value: 'trending', labelKey: 'browse.sortTrending' },
  { value: 'longest', labelKey: 'browse.sortLongest' },
  { value: 'oldest', labelKey: 'browse.sortOldest' },
]

export default function BrowsePage() {
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()

  const query = searchParams.get('q') || ''
  const category = searchParams.get('category') || ''
  const sort = searchParams.get('sort') || 'recent'
  const page = Number(searchParams.get('page') || 1)

  const params = useMemo(
    () => ({
      ...(query && { q: query }),
      ...(category && { category }),
      sort,
      page,
    }),
    [query, category, sort, page],
  )

  const { data: categories } = useCategories()
  const { data, isLoading, isError, error, refetch, isPlaceholderData } =
    useVideoList(params)

  const update = (changes) => {
    const next = new URLSearchParams(searchParams)
    Object.entries(changes).forEach(([key, value]) => {
      if (value) next.set(key, String(value))
      else next.delete(key)
    })
    // Any filter change invalidates the current page number.
    if (!('page' in changes)) next.delete('page')
    setSearchParams(next)
  }

  const results = data?.results ?? []
  const totalPages = data ? Math.ceil(data.count / 24) : 1

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-bold">
          {query ? t('browse.resultsFor', { query }) : t('browse.title')}
        </h1>
        {query && (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-400">
            <Info className="size-3.5" aria-hidden />
            {t('browse.searchNote')}
          </p>
        )}
      </header>

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => update({ category: '' })}
          className={cn(
            'rounded-full border px-3 py-1.5 text-xs font-medium transition',
            !category
              ? 'border-brand-500 bg-brand-500/15 text-brand-300'
              : 'border-ink-700 text-ink-300 hover:border-ink-600 hover:text-ink-100',
          )}
        >
          {t('browse.allCategories')}
        </button>

        {(categories ?? []).map((item) => (
          <button
            key={item.slug}
            type="button"
            onClick={() => update({ category: item.slug })}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition',
              category === item.slug
                ? 'border-brand-500 bg-brand-500/15 text-brand-300'
                : 'border-ink-700 text-ink-300 hover:border-ink-600 hover:text-ink-100',
            )}
          >
            {categoryLabel(item, t)}
            {item.video_count > 0 && (
              <span className="ml-1.5 text-ink-500">{item.video_count}</span>
            )}
          </button>
        ))}

        <label className="ml-auto flex items-center gap-2 text-xs text-ink-400">
          {t('browse.sort')}
          <select
            value={sort}
            onChange={(event) => update({ sort: event.target.value })}
            className="sv-input w-auto py-1.5 text-xs"
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading && <SkeletonGrid count={12} />}
      {isError && <ErrorState error={error} onRetry={refetch} />}

      {data && results.length === 0 && (
        <EmptyState
          icon={SearchX}
          title={t('browse.empty')}
          description={t('browse.emptyHint')}
        />
      )}

      {results.length > 0 && (
        <>
          <VideoGrid
            videos={results}
            className={isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}
          />

          {totalPages > 1 && (
            <nav className="mt-10 flex items-center justify-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                disabled={!data.previous}
                onClick={() => update({ page: page - 1 })}
              >
                {t('common.previous')}
              </Button>
              <span className="text-xs text-ink-400">
                {page} {t('common.of')} {totalPages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={!data.next}
                onClick={() => update({ page: page + 1 })}
              >
                {t('common.next')}
              </Button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
