import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const videoKeys = {
  feed: ['videos', 'feed'],
  list: (params) => ['videos', 'list', params],
  detail: (id) => ['videos', 'detail', id],
  playback: (id) => ['videos', 'playback', id],
  categories: ['catalog', 'categories'],
  tags: (q) => ['catalog', 'tags', q ?? ''],
  studioList: ['studio', 'videos'],
  studioDetail: (id) => ['studio', 'videos', id],
  studioStats: ['studio', 'stats'],
}

export function useHomeFeed() {
  return useQuery({
    queryKey: videoKeys.feed,
    queryFn: async () => (await api.get('/feed/')).data,
  })
}

export function useVideoList(params) {
  return useQuery({
    queryKey: videoKeys.list(params),
    queryFn: async () => (await api.get('/videos/', { params })).data,
    placeholderData: (previous) => previous, // keeps the grid stable while filtering
  })
}

export function useVideo(videoId) {
  return useQuery({
    queryKey: videoKeys.detail(videoId),
    queryFn: async () => (await api.get(`/videos/${videoId}/`)).data,
    enabled: Boolean(videoId),
  })
}

/**
 * Authorise one playback session.
 *
 * A mutation rather than a query on purpose: it is a POST that mints a
 * short-lived, single-session credential for private videos. Caching it and
 * replaying it later would hand the player expired presigned URLs.
 */
export function usePlayback(videoId) {
  return useQuery({
    queryKey: videoKeys.playback(videoId),
    queryFn: async () => (await api.post(`/videos/${videoId}/playback/`)).data,
    enabled: Boolean(videoId),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}

export function useCategories() {
  return useQuery({
    queryKey: videoKeys.categories,
    queryFn: async () => (await api.get('/catalog/categories/')).data,
    staleTime: 10 * 60_000, // the catalogue changes rarely
  })
}

export function useTagSuggestions(query) {
  return useQuery({
    queryKey: videoKeys.tags(query),
    queryFn: async () => (await api.get('/catalog/tags/', { params: { q: query } })).data,
    staleTime: 5 * 60_000,
  })
}

/* ---------------------------------------------------------------- studio */
export function useStudioVideos() {
  return useQuery({
    queryKey: videoKeys.studioList,
    queryFn: async () => (await api.get('/studio/videos/')).data,
    // Transcoding progress also arrives over WebSocket; this is the safety net
    // for a client whose socket failed to connect.
    refetchInterval: (query) => {
      const results = query.state.data?.results ?? []
      return results.some((video) => video.status === 'processing') ? 8000 : false
    },
  })
}

export function useStudioVideo(videoId) {
  return useQuery({
    queryKey: videoKeys.studioDetail(videoId),
    queryFn: async () => (await api.get(`/studio/videos/${videoId}/`)).data,
    enabled: Boolean(videoId),
  })
}

export function useStudioStats() {
  return useQuery({
    queryKey: videoKeys.studioStats,
    queryFn: async () => (await api.get('/studio/stats/')).data,
  })
}

export function useUpdateVideo(videoId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) =>
      (await api.patch(`/studio/videos/${videoId}/`, payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(videoKeys.studioDetail(videoId), data)
      queryClient.invalidateQueries({ queryKey: videoKeys.studioList })
      queryClient.invalidateQueries({ queryKey: videoKeys.detail(videoId) })
      queryClient.invalidateQueries({ queryKey: videoKeys.feed })
    },
  })
}

export function useDeleteVideo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (videoId) => api.delete(`/studio/videos/${videoId}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: videoKeys.studioList })
      queryClient.invalidateQueries({ queryKey: videoKeys.studioStats })
      queryClient.invalidateQueries({ queryKey: videoKeys.feed })
    },
  })
}

export function useRetryTranscode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (videoId) =>
      (await api.post(`/studio/videos/${videoId}/retry/`)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(videoKeys.studioDetail(data.id), data)
      queryClient.invalidateQueries({ queryKey: videoKeys.studioList })
    },
  })
}
