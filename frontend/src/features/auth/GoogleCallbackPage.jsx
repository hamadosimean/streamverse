import { XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { useNavigate, useSearchParams } from 'react-router-dom'

import AuthCard from '@/features/auth/AuthCard'
import { Button, Spinner } from '@/components/ui'
import { apiErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/stores/useAuthStore'

/**
 * Where Google sends the browser back to.
 *
 * The authorization code lands here in the query string and is exchanged by the
 * backend, which owns the client secret. The SPA's only jobs are to read the
 * query, hand it over, and get off this URL — which it does with `replace`, so
 * the code never sits in the history entry a Back button would return to.
 */
export default function GoogleCallbackPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const loginWithGoogle = useAuthStore((state) => state.loginWithGoogle)
  const [error, setError] = useState(null)

  // The code is single use. StrictMode mounts effects twice in development, and
  // the second exchange would fail against a spent code and show a false error.
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    attempted.current = true

    // Google reports a refusal in the query string rather than by failing the
    // redirect — most often `access_denied`, meaning the user backed out.
    const denied = params.get('error')
    if (denied) {
      setError(denied === 'access_denied'
        ? t('auth.googleCancelled')
        : t('auth.googleFailed'))
      return
    }

    const code = params.get('code')
    const state = params.get('state')
    if (!code || !state) {
      setError(t('auth.googleFailed'))
      return
    }

    loginWithGoogle(code, state)
      .then(({ created, next }) => {
        toast.success(created ? t('auth.welcomeNew') : t('auth.loggedIn'))
        navigate(next || '/', { replace: true })
      })
      .catch((exchangeError) => {
        setError(apiErrorMessage(exchangeError, t('auth.googleFailed')))
      })
  }, [loginWithGoogle, navigate, params, t])

  return (
    <AuthCard title={t('auth.loginTitle')}>
      {error ? (
        <div className="space-y-4 py-2">
          <p className="flex items-start gap-2 text-sm text-red-300">
            <XCircle className="mt-0.5 size-5 shrink-0" aria-hidden />
            {error}
          </p>
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => navigate('/login', { replace: true })}
          >
            {t('auth.backToLogin')}
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-3 py-4 text-sm text-ink-300">
          <Spinner />
          {t('auth.googleFinishing')}
        </div>
      )}
    </AuthCard>
  )
}
