import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import AppRoutes from '@/routes'
import { onForcedLogout } from '@/lib/api'
import { setLanguage } from '@/lib/i18n'
import { useAuthStore } from '@/stores/useAuthStore'
import { useUIStore } from '@/stores/useUIStore'

export default function App() {
  const { t } = useTranslation()
  const fetchUser = useAuthStore((state) => state.fetchUser)
  const language = useUIStore((state) => state.language)

  // Keep i18next and <html lang> in step with the persisted preference.
  useEffect(() => {
    setLanguage(language)
  }, [language])

  // Re-validate the persisted user on boot: a stored role is a rendering hint,
  // and the server is the only authority on whether the session is still good.
  useEffect(() => {
    fetchUser()
  }, [fetchUser])

  useEffect(
    () =>
      onForcedLogout((reason) => {
        toast.error(reason === 'suspended' ? t('auth.suspended') : t('auth.sessionExpired'))
      }),
    [t],
  )

  return <AppRoutes />
}
