import { CheckCircle2, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import AuthCard from '@/features/auth/AuthCard'
import { Button, Spinner } from '@/components/ui'
import { useAuthStore } from '@/stores/useAuthStore'

export default function ActivatePage() {
  const { t } = useTranslation()
  const { uid, token } = useParams()
  const navigate = useNavigate()
  const activate = useAuthStore((state) => state.activate)
  const [state, setState] = useState('pending') // pending | success | error
  // StrictMode mounts effects twice in development; the activation token is
  // single-use, so a second call would report a false failure.
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    attempted.current = true
    activate(uid, token)
      .then(() => setState('success'))
      .catch(() => setState('error'))
  }, [activate, uid, token])

  return (
    <AuthCard title={t('auth.registerTitle')}>
      {state === 'pending' && (
        <div className="flex items-center gap-3 py-4 text-sm text-ink-300">
          <Spinner />
          {t('auth.activating')}
        </div>
      )}

      {state === 'success' && (
        <div className="space-y-4 py-2">
          <p className="flex items-center gap-2 text-sm text-emerald-300">
            <CheckCircle2 className="size-5" aria-hidden />
            {t('auth.activated')}
          </p>
          <Button className="w-full" onClick={() => navigate('/login')}>
            {t('auth.submitLogin')}
          </Button>
        </div>
      )}

      {state === 'error' && (
        <div className="space-y-4 py-2">
          <p className="flex items-center gap-2 text-sm text-red-300">
            <XCircle className="size-5" aria-hidden />
            {t('auth.activationFailed')}
          </p>
          <Button variant="secondary" className="w-full" onClick={() => navigate('/register')}>
            {t('nav.register')}
          </Button>
        </div>
      )}
    </AuthCard>
  )
}
