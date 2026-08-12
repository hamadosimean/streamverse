import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'
import { videoKeys } from '@/features/videos/api'

export const engagementKeys = {
  reaction: (videoId) => ['engagement', 'reaction', videoId],
  comments: (videoId) => ['engagement', 'comments', videoId],
  related: (videoId) => ['engagement', 'related', videoId],
  reportReasons: ['engagement', 'report-reasons'],
  myReports: ['engagement', 'my-reports'],
  channel: (username) => ['channel', username],
  channelVideos: (username, sort) => ['channel', username, 'videos', sort],
  search: (params) => ['search', params],
  suggest: (q) => ['search', 'suggest', q],
}

/* ------------------------------------------------------------- reactions */
export function useReaction(videoId, { enabled = true } = {}) {
  return useQuery({
    queryKey: engagementKeys.reaction(videoId),
    queryFn: async () => (await api.get(`/videos/${videoId}/reaction/`)).data,
    enabled: Boolean(videoId) && enabled,
    staleTime: 0,
  })
}

export function useSetReaction(videoId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (reaction) =>
      (await api.post(`/videos/${videoId}/reaction/`, { reaction })).data,
    onSuccess: (data) => {
      queryClient.setQueryData(engagementKeys.reaction(videoId), data)
      // The detail payload carries like_count too; keep the two in step rather
      // than showing a stale number next to a freshly-toggled button.
      queryClient.setQueryData(videoKeys.detail(videoId), (previous) =>
        previous
          ? { ...previous, like_count: data.like_count,
              dislike_count: data.dislike_count }
          : previous,
      )
    },
  })
}

/* -------------------------------------------------------------- comments */
export function useComments(videoId) {
  return useInfiniteQuery({
    queryKey: engagementKeys.comments(videoId),
    queryFn: async ({ pageParam = 1 }) =>
      (await api.get(`/videos/${videoId}/comments/`, { params: { page: pageParam } }))
        .data,
    getNextPageParam: (lastPage, pages) => (lastPage.next ? pages.length + 1 : undefined),
    initialPageParam: 1,
    enabled: Boolean(videoId),
  })
}

export function useCreateComment(videoId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ content, parentComment }) =>
      (await api.post(`/videos/${videoId}/comments/`, {
        content,
        parent_comment: parentComment ?? null,
      })).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: engagementKeys.comments(videoId) })
      queryClient.invalidateQueries({ queryKey: videoKeys.detail(videoId) })
    },
  })
}

export function useUpdateComment(videoId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ commentId, content }) =>
      (await api.patch(`/comments/${commentId}/`, { content })).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: engagementKeys.comments(videoId) }),
  })
}

export function useDeleteComment(videoId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (commentId) => api.delete(`/comments/${commentId}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: engagementKeys.comments(videoId) })
      queryClient.invalidateQueries({ queryKey: videoKeys.detail(videoId) })
    },
  })
}

/* --------------------------------------------------------------- reports */
export function useReportReasons() {
  return useQuery({
    queryKey: engagementKeys.reportReasons,
    queryFn: async () => (await api.get('/reports/reasons/')).data.reasons,
    staleTime: 60 * 60_000, // a fixed vocabulary; no reason to refetch
  })
}

export function useCreateReport() {
  return useMutation({
    mutationFn: async ({ targetType, targetId, reason, details }) =>
      (await api.post('/reports/', {
        target_type: targetType,
        target_id: String(targetId),
        reason,
        details: details || '',
      })).data,
  })
}

/* --------------------------------------------------------------- related */
export function useRelatedVideos(videoId) {
  return useQuery({
    queryKey: engagementKeys.related(videoId),
    queryFn: async () => (await api.get(`/videos/${videoId}/related/`)).data,
    enabled: Boolean(videoId),
  })
}

/* --------------------------------------------------------------- channel */
export function useChannel(username) {
  return useQuery({
    queryKey: engagementKeys.channel(username),
    queryFn: async () => (await api.get(`/accounts/channels/${username}/`)).data,
    enabled: Boolean(username),
  })
}

export function useChannelVideos(username, sort = 'recent') {
  return useQuery({
    queryKey: engagementKeys.channelVideos(username, sort),
    queryFn: async () =>
      (await api.get(`/accounts/channels/${username}/videos/`, { params: { sort } })).data,
    enabled: Boolean(username),
  })
}

/* ---------------------------------------------------------------- search */
export function useSearch(params) {
  return useQuery({
    queryKey: engagementKeys.search(params),
    queryFn: async () => (await api.get('/search/', { params })).data,
    enabled: Boolean(params?.q),
    placeholderData: (previous) => previous,
  })
}

export function useSuggestions(query) {
  return useQuery({
    queryKey: engagementKeys.suggest(query),
    queryFn: async () => (await api.get('/search/suggest/', { params: { q: query } })).data,
    enabled: Boolean(query) && query.length >= 2,
    staleTime: 30_000,
  })
}
