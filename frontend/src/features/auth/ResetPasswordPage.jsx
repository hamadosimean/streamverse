import { zodResolver } from '@hookform/resolvers/zod'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import { useNavigate, useParams } from 'react-router-dom'
import { z } from 'zod'

import AuthCard from '@/features/auth/AuthCard'
import { Button, Field } from '@/components/ui'
import { api, apiErrorMessage } from '@/lib/api'

export default function ResetPasswordPage() {
  const { t } = useTranslation()
  const { uid, token } = useParams()
  const navigate = useNavigate()

  const schema = z
    .object({
      new_password: z.string().min(8, t('validation.passwordMin')),
      re_new_password: z.string().min(1, t('validation.required')),
    })
    .refine((data) => data.new_password === data.re_new_password, {
      message: t('validation.passwordMismatch'),
      path: ['re_new_password'],
    })

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema) })

  const onSubmit = async (values) => {
    try {
      await api.post(
        '/auth/users/reset_password_confirm/',
        { uid, token, ...values },
        { skipAuth: true },
      )
      toast.success(t('auth.resetDone'))
      navigate('/login')
    } catch (error) {
      setError('new_password', { message: apiErrorMessage(error) })
    }
  }

  return (
    <AuthCard title={t('auth.resetTitle')}>
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label={t('auth.resetNewPassword')} error={errors.new_password?.message} required>
          <input
            type="password"
            autoComplete="new-password"
            className="sv-input"
            {...register('new_password')}
          />
        </Field>
        <Field
          label={t('auth.passwordConfirm')}
          error={errors.re_new_password?.message}
          required
        >
          <input
            type="password"
            autoComplete="new-password"
            className="sv-input"
            {...register('re_new_password')}
          />
        </Field>
        <Button type="submit" loading={isSubmitting} className="w-full">
          {t('auth.resetSubmit')}
        </Button>
      </form>
    </AuthCard>
  )
}
