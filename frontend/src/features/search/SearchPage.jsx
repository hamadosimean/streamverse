import { Info, SearchX, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useDocumentMeta } from '@/hooks/useDocumentMeta'
import { useSearchParams } from 'react-router-dom'

import { VideoGrid } from '@/components/VideoCard'
import { Badge, EmptyState, ErrorState, SkeletonGrid } from '@/components/ui'
import { cn } from '@/lib/cn'
import { categoryLabel } from '@/lib/i18n'
import { useSearch } from '@/features/engagement/api'
import { useCategories } from '@/features/videos/api'

export default function SearchPage() {
  const { t } = useTranslation()
  // noindex: one indexable page per query string is unbounded crawl space with
  // no content of its own. robots.txt disallows /search too; this covers a
  // crawler that reaches the page from a link anyway.
  useDocumentMeta({ title: t('seo.searchTitle'), noindex: true })

  const [searchParams, setSearchParams] = useSearchParams()

  const query = searchParams.get('q') || ''
  const category = searchParams.get('category') || ''

  const { data: categories } = useCategories()
  const { data, isLoading, isError, error, refetch, isPlaceholderData } = useSearch({
    q: query,
    ...(category && { category }),
  })

  const update = (changes) => {
    const next = new URLSearchParams(searchParams)
    Object.entries(changes).forEach(([key, value]) => {
      if (value) next.set(key, value)
      else next.delete(key)
    })
    setSearchParams(next)
  }

  const results = data?.results ?? []

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-bold">
          {query ? t('browse.resultsFor', { query }) : t('search.title')}
        </h1>

        {data && query && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-400">
            <span>{t('search.resultCount', { count: data.count })}</span>
            {/* The mode is surfaced rather than hidden: an approximate match
                presented as an exact one is a small lie the user can act on. */}
            {data.mode === 'fuzzy' && (
              <Badge tone="warning">
                <Sparkles className="size-3" aria-hidden />
                {t('search.fuzzyMode')}
              </Badge>
            )}
            {data.mode === 'fulltext' && <Badge tone="success">{t('search.exactMode')}</Badge>}
          </div>
        )}
      </header>

      {!query && (
        <EmptyState
          icon={SearchX}
          title={t('search.emptyQuery')}
          description={t('search.emptyQueryHint')}
        />
      )}

      {query && (
        <>
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
              </button>
            ))}
          </div>

          {isLoading && <SkeletonGrid count={8} />}
          {isError && <ErrorState error={error} onRetry={refetch} />}

          {data && results.length === 0 && (
            <EmptyState
              icon={SearchX}
              title={t('browse.empty')}
              description={t('search.noResultsHint')}
            />
          )}

          {results.length > 0 && (
            <VideoGrid
              videos={results}
              className={isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}
            />
          )}

          <p className="mt-8 flex items-start gap-2 rounded-lg border border-ink-800 bg-ink-850 p-3 text-xs text-ink-400">
            <Info className="mt-0.5 size-3.5 shrink-0 text-brand-400" aria-hidden />
            {t('search.engineNote')}
          </p>
        </>
      )}
    </div>
  )
}
