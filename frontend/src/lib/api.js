import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || '/ws'

const ACCESS_KEY = 'sv.access'
const REFRESH_KEY = 'sv.refresh'

export const tokenStorage = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  set({ access, refresh }) {
    if (access) localStorage.setItem(ACCESS_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = tokenStorage.access
  if (token && !config.skipAuth) {
    config.headers.Authorization = `Bearer ${token}`
  }

  // The instance defaults to application/json, which is right for almost every
  // request and fatally wrong for file uploads: FormData must be sent as
  // multipart/form-data WITH the boundary the browser generates. Setting that
  // header by hand omits the boundary and the server cannot parse the body, so
  // the upload silently does nothing. Deleting it lets the browser fill it in.
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    delete config.headers['Content-Type']
    delete config.headers['content-type']
  }

  return config
})

// ---------------------------------------------------------------------------
// Refresh handling
//
// A page can fire several requests at once; if the access token has expired they
// would each independently try to refresh, and rotation (ROTATE_REFRESH_TOKENS
// + blacklist on the server) means only the first would succeed — the rest would
// log the user out. So: one refresh in flight, everyone else waits on it.
// ---------------------------------------------------------------------------
let refreshPromise = null
const logoutListeners = new Set()

export function onForcedLogout(listener) {
  logoutListeners.add(listener)
  return () => logoutListeners.delete(listener)
}

function forceLogout(reason) {
  tokenStorage.clear()
  logoutListeners.forEach((listener) => listener(reason))
}

async function refreshAccessToken() {
  const refresh = tokenStorage.refresh
  if (!refresh) throw new Error('no_refresh_token')

  const { data } = await axios.post(
    `${API_BASE_URL}/auth/jwt/refresh/`,
    { refresh },
    { headers: { 'Content-Type': 'application/json' } },
  )
  tokenStorage.set({ access: data.access, refresh: data.refresh })
  return data.access
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error
    if (!response || !config) return Promise.reject(error)

    const isAuthEndpoint = config.url?.includes('/auth/jwt/')
    const suspended = response.data?.code === 'account_suspended'

    if (response.status !== 401 || config._retried || isAuthEndpoint || config.skipAuth) {
      // A suspended account holds a technically valid token; only a logout clears it.
      if (suspended) forceLogout('suspended')
      return Promise.reject(error)
    }

    config._retried = true

    try {
      refreshPromise = refreshPromise || refreshAccessToken().finally(() => {
        refreshPromise = null
      })
      const access = await refreshPromise
      config.headers.Authorization = `Bearer ${access}`
      return api(config)
    } catch (refreshError) {
      forceLogout('expired')
      return Promise.reject(refreshError)
    }
  },
)

/**
 * Pull a displayable message out of the API's uniform error envelope
 * (`{detail, code, errors}` — see backend apps/core/exceptions.py).
 */
export function apiErrorMessage(error, fallback = 'Une erreur est survenue.') {
  const data = error?.response?.data
  if (!data) return error?.message || fallback
  if (typeof data === 'string') return data
  if (data.detail) return data.detail
  if (data.errors && typeof data.errors === 'object') {
    const first = Object.values(data.errors)[0]
    if (Array.isArray(first)) return first[0]
    if (typeof first === 'string') return first
  }
  return fallback
}

/** Field-level errors, ready to feed into react-hook-form's `setError`. */
export function apiFieldErrors(error) {
  const data = error?.response?.data
  const source = data?.errors ?? data
  if (!source || typeof source !== 'object') return {}
  return Object.fromEntries(
    Object.entries(source)
      .filter(([key]) => !['detail', 'code', 'errors'].includes(key))
      .map(([key, value]) => [key, Array.isArray(value) ? value[0] : String(value)]),
  )
}

/** Absolute WebSocket URL for a path, with the access token appended. */
export function websocketUrl(path) {
  const base = WS_BASE_URL.startsWith('ws')
    ? WS_BASE_URL
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${WS_BASE_URL}`
  const token = tokenStorage.access
  const url = `${base.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
  return token ? `${url}?token=${encodeURIComponent(token)}` : url
}
