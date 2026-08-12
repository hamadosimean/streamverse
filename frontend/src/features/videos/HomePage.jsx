import { ArrowRight, Clapperboard, Clock, Film, Flame, TrendingUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useDocumentMeta } from '@/hooks/useDocumentMeta'
import { Link } from 'react-router-dom'

import { VideoGrid } from '@/components/VideoCard'
import { Button, EmptyState, ErrorState, SkeletonGrid } from '@/components/ui'
import { useHomeFeed } from '@/features/videos/api'

function Section({ icon: Icon, title, videos }) {
  if (!videos?.length) return null
  return (
    <section className="mb-10">
      <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
        <Icon className="size-5 text-brand-400" aria-hidden />
        {title}
      </h2>
      <VideoGrid videos={videos} />
    </section>
  )
}

export default function HomePage() {
  const { t } = useTranslation()
  useDocumentMeta({
    title: null, // the site name alone is the right title for the root page
    description: t('seo.home'),
    canonical: `${window.location.origin}/`,
    // WebSite + SearchAction is what can earn a sitelinks search box. It is
    // emitted here rather than in index.html because a valid @id has to be an
    // absolute URL, and the origin is not known at build time.
    jsonLd: {
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      name: 'StreamVerse',
      url: `${window.location.origin}/`,
      potentialAction: {
        '@type': 'SearchAction',
        target: {
          '@type': 'EntryPoint',
          urlTemplate: `${window.location.origin}/search?q={search_term_string}`,
        },
        'query-input': 'required name=search_term_string',
      },
    },
  })

  const { data, isLoading, isError, error, refetch } = useHomeFeed()

  const isEmpty =
    data && !data.recent?.length && !data.trending?.length &&
    !data.most_viewed?.length && !data.shorts?.length

  return (
    <div>
      <section className="mb-10 overflow-hidden rounded-card border border-ink-800 bg-gradient-to-br from-brand-700/25 via-ink-850 to-accent-500/15 px-6 py-10 sm:px-10 sm:py-14">
        <h1 className="max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
          {t('home.heroTitle')}
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-ink-300 sm:text-base">
          {t('home.heroSubtitle')}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/browse">
            <Button>
              {t('home.browseAll')}
              <ArrowRight className="size-4" aria-hidden />
            </Button>
          </Link>
          <Link to="/upload">
            <Button variant="secondary">{t('nav.upload')}</Button>
          </Link>
        </div>
      </section>

      {isLoading && <SkeletonGrid count={8} />}

      {isError && <ErrorState error={error} onRetry={refetch} />}

      {isEmpty && (
        <EmptyState
          icon={Film}
          title={t('home.empty')}
          description={t('home.emptyHint')}
          action={
            <Link to="/upload">
              <Button size="sm">{t('nav.upload')}</Button>
            </Link>
          }
        />
      )}

      {data?.shorts?.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
            <Clapperboard className="size-5 text-brand-400" aria-hidden />
            {t('nav.shorts')}
            <Link to="/shorts" className="ml-auto text-xs font-normal text-brand-300 hover:underline">
              {t('shorts.seeAll')}
            </Link>
          </h2>
          {/* Portrait thumbnails in their own rail — a vertical clip cropped
              into a 16:9 grid cell shows a sliver of the frame. */}
          <div className="flex gap-4 overflow-x-auto pb-2">
            {data.shorts.map((short) => (
              <Link key={short.id} to={`/shorts/${short.id}`}
                    className="group w-[150px] shrink-0">
                <div className="aspect-[9/16] w-full overflow-hidden rounded-card bg-ink-800">
                  {short.poster_url && (
                    <img src={short.poster_url} alt="" loading="lazy"
                         className="size-full object-cover transition group-hover:scale-105" />
                  )}
                </div>
                <p className="mt-2 line-clamp-2 text-xs font-medium group-hover:text-brand-300">
                  {short.title}
                </p>
              </Link>
            ))}
          </div>
        </section>
      )}

      {data && !isEmpty && (
        <>
          <Section icon={Clock} title={t('home.recent')} videos={data.recent} />
          <Section icon={Flame} title={t('home.trending')} videos={data.trending} />
          <Section icon={TrendingUp} title={t('home.mostViewed')} videos={data.most_viewed} />
        </>
      )}
    </div>
  )
}
