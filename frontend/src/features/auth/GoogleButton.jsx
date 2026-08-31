import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import { apiErrorMessage } from '@/lib/api'
import { cn } from '@/lib/cn'
import { startGoogleLogin, useAuthProviders } from '@/features/auth/googleAuth'

/** Google's own G mark. Inline so it needs no request and no CSP exception. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden focusable="false">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.28-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.55 10.78l7.98-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  )
}

/**
 * "Continue with Google" — renders nothing at all when the deployment has no
 * Google credentials, so a demo instance does not show a button that can only
 * fail.
 *
 * `next` is the path to return to after the round trip, normally wherever the
 * user was headed when they were bounced to /login.
 */
export default function GoogleButton({ next = '/', className }) {
  const { t } = useTranslation()
  const { data: providers } = useAuthProviders()
  const [leaving, setLeaving] = useState(false)

  if (!providers?.google?.enabled) return null

  const onClick = async () => {
    setLeaving(true)
    try {
      await startGoogleLogin(next)
      // No reset on success: the page is on its way out, and re-enabling the
      // button would only invite a second click that starts a second flow.
    } catch (error) {
      setLeaving(false)
      toast.error(apiErrorMessage(error, t('auth.googleFailed')))
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={leaving}
      className={cn(
        'inline-flex w-full items-center justify-center gap-3 rounded-lg',
        'border border-ink-700 bg-ink-800 px-4 py-2.5 text-sm font-medium',
        'transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-60',
        className,
      )}
    >
      <GoogleMark />
      {leaving ? t('auth.googleConnecting') : t('auth.continueWithGoogle')}
    </button>
  )
}

/** A labelled rule, for separating the Google button from the e-mail form. */
export function AuthDivider() {
  const { t } = useTranslation()
  return (
    <div className="my-5 flex items-center gap-3" aria-hidden>
      <span className="h-px flex-1 bg-ink-700" />
      <span className="text-xs uppercase tracking-wide text-ink-400">
        {t('auth.or')}
      </span>
      <span className="h-px flex-1 bg-ink-700" />
    </div>
  )
}
