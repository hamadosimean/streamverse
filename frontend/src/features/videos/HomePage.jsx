import { ArrowRight, Clock, Film, Flame, TrendingUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
  const { data, isLoading, isError, error, refetch } = useHomeFeed()

  const isEmpty =
    data && !data.recent?.length && !data.trending?.length && !data.most_viewed?.length

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
