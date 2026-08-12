import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const libraryKeys = {
  summary: ['library', 'summary'],
  history: (resumable) => ['library', 'history', resumable ? 'resumable' : 'all'],
  bookmarks: ['library', 'bookmarks'],
  liked: ['library', 'liked'],
  following: ['library', 'following'],
  feed: ['library', 'feed'],
  followState: (username) => ['library', 'follow', username],
  bookmarkState: (videoId) => ['library', 'bookmark', videoId],
}

export function useLibrarySummary({ enabled = true } = {}) {
  return useQuery({
    queryKey: libraryKeys.summary,
    queryFn: async () => (await api.get('/library/')).data,
    enabled,
  })
}

export function useWatchHistory({ resumable = false } = {}) {
  return useQuery({
    queryKey: libraryKeys.history(resumable),
    queryFn: async () =>
      (await api.get('/library/history/', {
        params: resumable ? { resumable: 'true' } : {},
      })).data,
  })
}

export function useClearHistory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => api.delete('/library/history/'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['library'] }),
  })
}

export function useRemoveFromHistory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (videoId) => api.delete(`/library/history/${videoId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['library'] }),
  })
}

export function useBookmarks() {
  return useQuery({
    queryKey: libraryKeys.bookmarks,
    queryFn: async () => (await api.get('/library/bookmarks/')).data,
  })
}

export function useToggleBookmark() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (videoId) =>
      (await api.post(`/videos/${videoId}/bookmark/`)).data,
    onSuccess: (data, videoId) => {
      queryClient.setQueryData(libraryKeys.bookmarkState(videoId), data)
      queryClient.invalidateQueries({ queryKey: libraryKeys.bookmarks })
      queryClient.invalidateQueries({ queryKey: libraryKeys.summary })
      // The watch page carries is_bookmarked on the video payload.
      queryClient.invalidateQueries({ queryKey: ['videos', 'detail', videoId] })
    },
  })
}

export function useLikedVideos() {
  return useQuery({
    queryKey: libraryKeys.liked,
    queryFn: async () => (await api.get('/library/likes/')).data,
  })
}

export function useFollowing() {
  return useQuery({
    queryKey: libraryKeys.following,
    queryFn: async () => (await api.get('/library/following/')).data,
  })
}

export function useFollowingFeed() {
  return useQuery({
    queryKey: libraryKeys.feed,
    queryFn: async () => (await api.get('/library/feed/')).data,
  })
}

export function useToggleFollow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (username) =>
      (await api.post(`/accounts/channels/${username}/follow/`)).data,
    onSuccess: (data, username) => {
      queryClient.setQueryData(libraryKeys.followState(username), data)
      queryClient.invalidateQueries({ queryKey: libraryKeys.following })
      queryClient.invalidateQueries({ queryKey: libraryKeys.feed })
      queryClient.invalidateQueries({ queryKey: libraryKeys.summary })
      queryClient.invalidateQueries({ queryKey: ['channel', username] })
      // The watch page carries is_following_uploader.
      queryClient.invalidateQueries({ queryKey: ['videos', 'detail'] })
    },
  })
}
