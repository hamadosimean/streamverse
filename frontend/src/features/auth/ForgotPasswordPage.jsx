import { zodResolver } from '@hookform/resolvers/zod'
import { MailCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import AuthCard from '@/features/auth/AuthCard'
import { Button, Field } from '@/components/ui'
import { api } from '@/lib/api'

export default function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [sent, setSent] = useState(false)

  const schema = z.object({
    email: z.string().min(1, t('validation.required')).email(t('validation.email')),
  })

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema) })

  const onSubmit = async ({ email }) => {
    // Always report success: telling an anonymous caller whether an address is
    // registered is an account-enumeration oracle.
    try {
      await api.post('/auth/users/reset_password/', { email }, { skipAuth: true })
    } catch {
      /* deliberately ignored */
    }
    setSent(true)
  }

  return (
    <AuthCard
      title={t('auth.resetTitle')}
      subtitle={t('auth.resetSubtitle')}
      footer={
        <Link to="/login" className="font-medium text-brand-300 hover:underline">
          {t('nav.login')}
        </Link>
      }
    >
      {sent ? (
        <p className="flex items-start gap-2 py-2 text-sm text-emerald-300">
          <MailCheck className="mt-0.5 size-5 shrink-0" aria-hidden />
          {t('auth.resetSent')}
        </p>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          <Field label={t('auth.email')} error={errors.email?.message} required>
            <input type="email" autoComplete="email" className="sv-input" {...register('email')} />
          </Field>
          <Button type="submit" loading={isSubmitting} className="w-full">
            {t('auth.resetSend')}
          </Button>
        </form>
      )}
    </AuthCard>
  )
}
