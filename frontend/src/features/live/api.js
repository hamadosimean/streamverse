import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const liveKeys = {
  list: ['live', 'list'],
  detail: (slug) => ['live', 'detail', slug],
  mine: ['live', 'mine'],
  sessions: ['live', 'sessions'],
}

export function useLiveChannels() {
  return useQuery({
    queryKey: liveKeys.list,
    queryFn: async () => (await api.get('/live/')).data,
    // A channel can go live at any moment and there is no push channel for the
    // *list*; a short poll is the honest way to keep it current.
    refetchInterval: 20_000,
  })
}

export function useLiveChannel(slug) {
  return useQuery({
    queryKey: liveKeys.detail(slug),
    queryFn: async () => (await api.get(`/live/${slug}/`)).data,
    enabled: Boolean(slug),
    // Status changes arrive over the WebSocket; this is the fallback for a
    // client whose socket could not connect.
    refetchInterval: 30_000,
  })
}

export function useMyLiveChannel() {
  return useQuery({
    queryKey: liveKeys.mine,
    queryFn: async () => (await api.get('/live/me/')).data,
  })
}

export function useUpdateMyLiveChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => (await api.patch('/live/me/', payload)).data,
    onSuccess: (data) => queryClient.setQueryData(liveKeys.mine, data),
  })
}

export function useRotateStreamKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post('/live/me/rotate-key/')).data,
    onSuccess: (data) => queryClient.setQueryData(liveKeys.mine, data),
  })
}

export function useMyLiveSessions() {
  return useQuery({
    queryKey: liveKeys.sessions,
    queryFn: async () => (await api.get('/live/me/sessions/')).data,
  })
}
