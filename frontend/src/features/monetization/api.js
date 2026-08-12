import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export const billingKeys = {
  plans: ['billing', 'plans'],
  providers: ['billing', 'providers'],
  subscription: ['billing', 'subscription'],
  transaction: (id) => ['billing', 'transaction', id],
  campaigns: (status) => ['admin', 'campaigns', status ?? 'all'],
  campaignStats: ['admin', 'campaigns', 'stats'],
}

export function usePlans() {
  return useQuery({
    queryKey: billingKeys.plans,
    queryFn: async () => (await api.get('/monetization/plans/')).data,
    staleTime: 10 * 60_000,
  })
}

export function usePaymentProviders() {
  return useQuery({
    queryKey: billingKeys.providers,
    queryFn: async () => (await api.get('/monetization/providers/')).data,
    staleTime: 10 * 60_000,
  })
}

export function useMySubscription() {
  return useQuery({
    queryKey: billingKeys.subscription,
    queryFn: async () => (await api.get('/monetization/subscription/')).data,
  })
}

export function useCheckout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) =>
      (await api.post('/monetization/checkout/', payload)).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: billingKeys.subscription }),
  })
}

/**
 * Poll one transaction until it settles.
 *
 * Polling rather than a socket: a payment confirmation is a single state change
 * the user waits seconds for, and a WebSocket per checkout would be more
 * machinery than the problem needs. The interval stops itself once the
 * transaction reaches a terminal state.
 */
export function useTransactionStatus(transactionId, { enabled = true } = {}) {
  return useQuery({
    queryKey: billingKeys.transaction(transactionId),
    queryFn: async () =>
      (await api.get(`/monetization/transactions/${transactionId}/`)).data,
    enabled: Boolean(transactionId) && enabled,
    refetchInterval: (query) =>
      query.state.data?.status === 'pending' ? 2000 : false,
  })
}

export function useCancelSubscription() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.delete('/monetization/subscription/')).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: billingKeys.subscription }),
  })
}

/* --------------------------------------------------------------- ad admin */
export function useAdCampaigns(status) {
  return useQuery({
    queryKey: billingKeys.campaigns(status),
    queryFn: async () =>
      (await api.get('/admin/ad-campaigns/', { params: status ? { status } : {} })).data,
  })
}

export function useAdStats() {
  return useQuery({
    queryKey: billingKeys.campaignStats,
    queryFn: async () => (await api.get('/admin/ad-campaigns/stats/')).data,
  })
}

export function useSaveCampaign() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, payload }) => {
      // No explicit Content-Type: the request interceptor strips the JSON
      // default for FormData so the browser can set multipart + boundary.
      const url = id ? `/admin/ad-campaigns/${id}/` : '/admin/ad-campaigns/'
      const method = id ? api.patch : api.post
      return (await method(url, payload)).data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'campaigns'] })
    },
  })
}

export function useDeleteCampaign() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id) => api.delete(`/admin/ad-campaigns/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'campaigns'] }),
  })
}

/* ------------------------------------------------------------ ad playback */
export async function fetchAdPlan(videoId) {
  const { data } = await api.post(`/videos/${videoId}/ads/`)
  return data
}

export async function reportAdEvent(impressionId, event) {
  try {
    await api.post(`/ads/impressions/${impressionId}/`, event)
  } catch {
    // Ad telemetry must never break playback.
  }
}
