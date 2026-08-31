import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

/**
 * Which sign-in providers this deployment offers.
 *
 * Asked of the server rather than read from a build-time env var: the client id
 * lives in the backend's configuration, and a second copy in the frontend build
 * would be one more thing to keep in step — and would go stale the moment
 * someone enables Google without rebuilding the SPA.
 */
export function useAuthProviders() {
  return useQuery({
    queryKey: ['auth', 'providers'],
    queryFn: async () => {
      const { data } = await api.get('/auth/providers/', { skipAuth: true })
      return data
    },
    staleTime: Infinity,
    // A failure here must not block the password form; the caller treats a
    // missing answer as "no providers".
    retry: false,
  })
}

/**
 * Leave for Google's consent screen.
 *
 * `next` is where to come back to once the round trip is done. It is handed to
 * the server, parked with the OAuth state, and validated again on the way back
 * — it never travels through the URL the user's browser carries to Google.
 *
 * The navigation is a real one, not an iframe or a popup: signing in to Google
 * inside a frame we control is exactly the shape of a credential-phishing page,
 * and the user should see accounts.google.com in the address bar.
 */
export async function startGoogleLogin(next = '/') {
  const { data } = await api.get('/auth/google/authorize/', {
    params: { next },
    skipAuth: true,
  })
  window.location.assign(data.authorization_url)
}
