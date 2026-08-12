import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { api, onForcedLogout, tokenStorage } from '@/lib/api'

/**
 * Auth state.
 *
 * The user object is persisted so a reload renders the header immediately
 * instead of flashing a logged-out state, but it is always re-fetched in the
 * background — a persisted role is a rendering hint, never an authorisation.
 * Every gate is enforced server-side.
 */
export const useAuthStore = create()(
  persist(
    (set, get) => ({
      user: null,
      status: 'idle', // idle | loading | authenticated | anonymous

      isAuthenticated: () => Boolean(get().user),
      isAdmin: () => get().user?.role === 'admin',
      isModerator: () => ['admin', 'moderator'].includes(get().user?.role),

      async login(email, password) {
        const { data } = await api.post(
          '/auth/jwt/create/',
          { email, password },
          { skipAuth: true },
        )
        tokenStorage.set({ access: data.access, refresh: data.refresh })
        await get().fetchUser()
        return get().user
      },

      async register(payload) {
        const { data } = await api.post('/auth/users/', payload, { skipAuth: true })
        return data
      },

      async activate(uid, token) {
        await api.post('/auth/users/activation/', { uid, token }, { skipAuth: true })
      },

      async fetchUser() {
        if (!tokenStorage.access) {
          set({ user: null, status: 'anonymous' })
          return null
        }
        set({ status: 'loading' })
        try {
          const { data } = await api.get('/accounts/me/')
          set({ user: data, status: 'authenticated' })
          return data
        } catch {
          set({ user: null, status: 'anonymous' })
          return null
        }
      },

      async updateProfile(payload) {
        const { data } = await api.patch('/accounts/me/', payload)
        set({ user: data })
        return data
      },

      logout() {
        tokenStorage.clear()
        set({ user: null, status: 'anonymous' })
      },
    }),
    {
      name: 'sv.auth',
      partialize: (state) => ({ user: state.user }),
    },
  ),
)

// The axios interceptor cannot import the store (circular), so it publishes
// forced logouts through a listener instead.
onForcedLogout(() => {
  useAuthStore.setState({ user: null, status: 'anonymous' })
})
