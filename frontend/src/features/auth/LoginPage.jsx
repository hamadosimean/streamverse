import { zodResolver } from '@hookform/resolvers/zod'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import AuthCard from '@/features/auth/AuthCard'
import GoogleButton, { AuthDivider } from '@/features/auth/GoogleButton'
import { Button, Field } from '@/components/ui'
import { apiErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/stores/useAuthStore'

export default function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const login = useAuthStore((state) => state.login)

  // Where the user was headed before the auth gate sent them here. Google takes
  // the browser off-site and back, so this has to survive the round trip on the
  // server rather than in router state, which does not.
  const next = location.state?.from?.pathname || '/'

  const schema = z.object({
    email: z.string().min(1, t('validation.required')).email(t('validation.email')),
    password: z.string().min(1, t('validation.required')),
  })

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema) })

  const onSubmit = async ({ email, password }) => {
    try {
      await login(email, password)
      toast.success(t('auth.loggedIn'))
      navigate(next, { replace: true })
    } catch (error) {
      // Djoser answers a bad pair with a generic 401 — surface it on the form
      // rather than as a toast that disappears.
      setError('password', { message: apiErrorMessage(error, t('common.error')) })
    }
  }

  return (
    <AuthCard
      title={t('auth.loginTitle')}
      subtitle={t('auth.loginSubtitle')}
      footer={
        <>
          {t('auth.noAccount')}{' '}
          <Link to="/register" className="font-medium text-brand-300 hover:underline">
            {t('nav.register')}
          </Link>
        </>
      }
    >
      <GoogleButton next={next} />
      <AuthDivider />

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label={t('auth.email')} error={errors.email?.message} required>
          <input
            type="email"
            autoComplete="email"
            className="sv-input"
            placeholder="vous@exemple.com"
            {...register('email')}
          />
        </Field>

        <Field label={t('auth.password')} error={errors.password?.message} required>
          <input
            type="password"
            autoComplete="current-password"
            className="sv-input"
            {...register('password')}
          />
        </Field>

        <div className="mb-4 text-right">
          <Link
            to="/password/forgot"
            className="text-xs text-ink-400 transition hover:text-brand-300"
          >
            {t('auth.forgotPassword')}
          </Link>
        </div>

        <Button type="submit" loading={isSubmitting} className="w-full">
          {t('auth.submitLogin')}
        </Button>
      </form>
    </AuthCard>
  )
}
