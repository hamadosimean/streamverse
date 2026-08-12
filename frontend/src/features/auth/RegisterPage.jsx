import { zodResolver } from '@hookform/resolvers/zod'
import { Info } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import AuthCard from '@/features/auth/AuthCard'
import { Button, Field } from '@/components/ui'
import { apiErrorMessage, apiFieldErrors } from '@/lib/api'
import { useAuthStore } from '@/stores/useAuthStore'
import { useUIStore } from '@/stores/useUIStore'

export default function RegisterPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const registerUser = useAuthStore((state) => state.register)
  const language = useUIStore((state) => state.language)
  const [submitted, setSubmitted] = useState(false)

  const schema = z
    .object({
      email: z.string().min(1, t('validation.required')).email(t('validation.email')),
      username: z
        .string()
        .min(3, t('validation.min', { count: 3 }))
        .max(30, t('validation.max', { count: 30 }))
        .regex(/^[a-z0-9][a-z0-9_-]*$/, t('validation.usernamePattern')),
      display_name: z.string().max(80, t('validation.max', { count: 80 })).optional(),
      password: z.string().min(8, t('validation.passwordMin')),
      re_password: z.string().min(1, t('validation.required')),
    })
    .refine((data) => data.password === data.re_password, {
      message: t('validation.passwordMismatch'),
      path: ['re_password'],
    })

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema) })

  const onSubmit = async (values) => {
    try {
      await registerUser({ ...values, preferred_language: language })
      setSubmitted(true)
      toast.success(t('auth.registered'))
    } catch (error) {
      // Map Django/Djoser field errors back onto the form fields that produced
      // them, so "this username is taken" lands on the username input.
      const fields = apiFieldErrors(error)
      const known = ['email', 'username', 'password', 're_password', 'display_name']
      let matched = false
      Object.entries(fields).forEach(([key, message]) => {
        if (known.includes(key)) {
          setError(key, { message })
          matched = true
        }
      })
      if (!matched) toast.error(apiErrorMessage(error))
    }
  }

  if (submitted) {
    return (
      <AuthCard title={t('auth.registerTitle')}>
        <div className="space-y-4 text-sm">
          <p className="text-emerald-300">{t('auth.registered')}</p>
          <p className="flex items-start gap-2 rounded-lg border border-ink-700 bg-ink-800 p-3 text-xs text-ink-300">
            <Info className="mt-0.5 size-4 shrink-0 text-brand-400" aria-hidden />
            {t('auth.registeredMailpit')}
          </p>
          <Button className="w-full" onClick={() => navigate('/login')}>
            {t('auth.submitLogin')}
          </Button>
        </div>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title={t('auth.registerTitle')}
      subtitle={t('auth.registerSubtitle')}
      footer={
        <>
          {t('auth.hasAccount')}{' '}
          <Link to="/login" className="font-medium text-brand-300 hover:underline">
            {t('nav.login')}
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label={t('auth.email')} error={errors.email?.message} required>
          <input type="email" autoComplete="email" className="sv-input" {...register('email')} />
        </Field>

        <Field
          label={t('auth.username')}
          error={errors.username?.message}
          hint={t('auth.usernameHint')}
          required
        >
          <input
            type="text"
            autoComplete="username"
            className="sv-input"
            placeholder="mon-pseudo"
            {...register('username')}
          />
        </Field>

        <Field label={t('auth.displayName')} error={errors.display_name?.message}>
          <input type="text" className="sv-input" {...register('display_name')} />
        </Field>

        <Field label={t('auth.password')} error={errors.password?.message} required>
          <input
            type="password"
            autoComplete="new-password"
            className="sv-input"
            {...register('password')}
          />
        </Field>

        <Field label={t('auth.passwordConfirm')} error={errors.re_password?.message} required>
          <input
            type="password"
            autoComplete="new-password"
            className="sv-input"
            {...register('re_password')}
          />
        </Field>

        <Button type="submit" loading={isSubmitting} className="w-full">
          {t('auth.submitRegister')}
        </Button>
      </form>
    </AuthCard>
  )
}
