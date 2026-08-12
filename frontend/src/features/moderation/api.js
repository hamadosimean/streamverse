import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const moderationKeys = {
  queue: (params) => ['moderation', 'queue', params],
  report: (id) => ['moderation', 'report', id],
  stats: ['moderation', 'stats'],
  log: ['moderation', 'log'],
  user: (username) => ['moderation', 'user', username],
  dashboard: ['admin', 'dashboard'],
}

export function useReportQueue(params) {
  return useQuery({
    queryKey: moderationKeys.queue(params),
    queryFn: async () => (await api.get('/moderation/reports/', { params })).data,
    // A queue is a live worklist; a stale one has two moderators picking up the
    // same report.
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })
}

export function useReport(reportId) {
  return useQuery({
    queryKey: moderationKeys.report(reportId),
    queryFn: async () => (await api.get(`/moderation/reports/${reportId}/`)).data,
    enabled: Boolean(reportId),
  })
}

export function useResolveReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ reportId, ...payload }) =>
      (await api.post(`/moderation/reports/${reportId}/`, payload)).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['moderation'] })
    },
  })
}

export function useModerationStats() {
  return useQuery({
    queryKey: moderationKeys.stats,
    queryFn: async () => (await api.get('/moderation/stats/')).data,
    refetchInterval: 60_000,
  })
}

export function useModerationLog(action) {
  return useQuery({
    queryKey: [...moderationKeys.log, action ?? 'all'],
    queryFn: async () =>
      (await api.get('/moderation/log/', { params: action ? { action } : {} })).data,
  })
}

export function useModeratedUser(username) {
  return useQuery({
    queryKey: moderationKeys.user(username),
    queryFn: async () => (await api.get(`/moderation/users/${username}/`)).data,
    enabled: Boolean(username),
  })
}

export function useSanction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) =>
      (await api.post('/moderation/sanctions/', payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['moderation'] }),
  })
}

export function useAdminDashboard() {
  return useQuery({
    queryKey: moderationKeys.dashboard,
    queryFn: async () => (await api.get('/admin/dashboard/')).data,
  })
}
