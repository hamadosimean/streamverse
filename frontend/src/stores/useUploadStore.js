import * as tus from 'tus-js-client'
import { create } from 'zustand'

import { API_BASE_URL, api, tokenStorage } from '@/lib/api'

/**
 * Resumable upload queue (tus 1.0.0).
 *
 * Why resumable at all: a 2 GB single-shot form POST that dies at 90% has to
 * start over. tus stores the offset server-side, so a dropped connection resumes
 * from the last committed byte — and tus-js-client keeps the upload URL in
 * localStorage, so it survives a page reload too.
 *
 * The store owns the queue; the Upload instances live outside React state
 * because they are not serialisable and must not be cloned on every render.
 */
const uploadInstances = new Map()

const CHUNK_SIZE = 8 * 1024 * 1024 // 8 MiB — small enough to retry cheaply

let counter = 0
const nextId = () => `upload-${Date.now()}-${(counter += 1)}`

export const useUploadStore = create((set, get) => ({
  // { id, filename, size, bytesUploaded, percent, status, videoId, error }
  queue: [],

  patch(id, changes) {
    set((state) => ({
      queue: state.queue.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    }))
  },

  /**
   * Queue a file. `meta` carries the title/description the user typed, which the
   * backend copies onto the created Video.
   */
  start(file, meta = {}) {
    const id = nextId()

    set((state) => ({
      queue: [
        {
          id,
          filename: file.name,
          size: file.size,
          bytesUploaded: 0,
          percent: 0,
          status: 'uploading',
          videoId: null,
          error: null,
          title: meta.title || file.name,
        },
        ...state.queue,
      ],
    }))

    const upload = new tus.Upload(file, {
      endpoint: `${window.location.origin}${API_BASE_URL}/uploads/`,
      chunkSize: CHUNK_SIZE,
      // Backoff on transient network failures rather than surfacing them.
      retryDelays: [0, 1000, 3000, 5000, 10000, 20000],
      // Lets tus-js-client find and resume this exact upload after a reload.
      storeFingerprintForResuming: true,
      removeFingerprintOnSuccess: true,
      metadata: {
        filename: file.name,
        filetype: file.type || 'application/octet-stream',
        title: meta.title || file.name,
        description: meta.description || '',
      },

      // The access token is short-lived; re-read it before every request so a
      // long upload does not die on an expiry it could have survived.
      onBeforeRequest(req) {
        const token = tokenStorage.access
        if (token) req.setHeader('Authorization', `Bearer ${token}`)
      },

      async onShouldRetry(error) {
        const status = error?.originalResponse?.getStatus?.()
        if (status === 401) {
          // Bounce a normal API call through the axios interceptor, which owns
          // the single-flight refresh, then let tus retry with the new token.
          try {
            await api.get('/accounts/me/')
            return true
          } catch {
            return false
          }
        }
        // 4xx other than 401/409 means the server rejected the file itself —
        // retrying would only repeat the rejection.
        if (status && status >= 400 && status < 500 && status !== 409) return false
        return true
      },

      onProgress(bytesUploaded, bytesTotal) {
        get().patch(id, {
          bytesUploaded,
          percent: bytesTotal ? Math.round((bytesUploaded / bytesTotal) * 100) : 0,
        })
      },

      onError(error) {
        const detail =
          safeJson(error?.originalResponse?.getBody?.())?.detail || error?.message
        get().patch(id, { status: 'error', error: detail || 'Televersement echoue.' })
        uploadInstances.delete(id)
      },

      async onSuccess(payload) {
        // The server returns the created Video id on the final PATCH; the
        // dedicated endpoint below is the fallback for proxies that strip
        // non-standard response headers.
        let videoId = payload?.lastResponse?.getHeader?.('StreamVerse-Video-Id') || null
        if (!videoId) {
          videoId = await resolveVideoId(upload.url)
        }
        get().patch(id, {
          status: 'processing',
          percent: 100,
          videoId,
        })
        uploadInstances.delete(id)
      },
    })

    // Resume rather than restart if this exact file was uploaded before.
    upload.findPreviousUploads().then((previous) => {
      if (previous.length > 0) upload.resumeFromPreviousUpload(previous[0])
      upload.start()
    })

    uploadInstances.set(id, upload)
    return id
  },

  pause(id) {
    uploadInstances.get(id)?.abort()
    get().patch(id, { status: 'paused' })
  },

  resume(id) {
    const upload = uploadInstances.get(id)
    if (!upload) return
    upload.start()
    get().patch(id, { status: 'uploading', error: null })
  },

  async cancel(id) {
    const upload = uploadInstances.get(id)
    if (upload) {
      await upload.abort(true) // `true` also DELETEs the server-side session
      uploadInstances.delete(id)
    }
    set((state) => ({ queue: state.queue.filter((item) => item.id !== id) }))
  },

  remove(id) {
    uploadInstances.delete(id)
    set((state) => ({ queue: state.queue.filter((item) => item.id !== id) }))
  },

  clearFinished() {
    set((state) => ({
      queue: state.queue.filter((item) => !['processing', 'error'].includes(item.status)),
    }))
  },
}))

function safeJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

async function resolveVideoId(uploadUrl) {
  if (!uploadUrl) return null
  const match = uploadUrl.match(/\/uploads\/([0-9a-f-]{36})\/?$/i)
  if (!match) return null
  try {
    const { data } = await api.get(`/uploads/${match[1]}/video/`)
    return data.video_id
  } catch {
    return null
  }
}
