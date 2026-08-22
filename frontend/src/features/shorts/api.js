import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const shortsKeys = {
  feed: (params) => ['shorts', 'feed', params],
  detail: (id) => ['shorts', 'detail', id],
}

/**
 * The Shorts feed.
 *
 * `staleTime` is deliberately long: the feed is a scroll surface, and a
 * background refetch that reorders the list under the viewer's thumb is worse
 * than slightly stale data.
 */
export function useShortsFeed({ sort = 'shuffle', start, category, seed } = {}) {
  // `seed` only means anything to the shuffle ordering; sending it with an
  // explicit sort would fragment the query cache for no reason.
  const params = {
    sort,
    ...(sort === 'shuffle' && seed && { seed }),
    ...(start && { start }),
    ...(category && { category }),
  }
  return useQuery({
    queryKey: shortsKeys.feed(params),
    queryFn: async () => (await api.get('/shorts/', { params })).data,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  })
}

export function useShort(videoId) {
  return useQuery({
    queryKey: shortsKeys.detail(videoId),
    queryFn: async () => (await api.get(`/shorts/${videoId}/`)).data,
    enabled: Boolean(videoId),
  })
}
