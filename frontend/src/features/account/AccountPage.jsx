import { zodResolver } from '@hookform/resolvers/zod'
import { KeyRound, Link2, LogOut, UserCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { z } from 'zod'

import Avatar from '@/components/Avatar'
import { Badge, Button, Field } from '@/components/ui'
import ProfileImagesCard from '@/features/account/ProfileImagesCard'
import { api, apiErrorMessage, apiFieldErrors } from '@/lib/api'
import { formatAbsolute } from '@/lib/format'
import { useAuthStore } from '@/stores/useAuthStore'
import { useUIStore } from '@/stores/useUIStore'

function ProfileForm() {
  const { t, i18n } = useTranslation()
  const { user, updateProfile } = useAuthStore()
  const setLanguage = useUIStore((state) => state.setLanguage)

  const schema = z.object({
    display_name: z.string().max(80, t('validation.max', { count: 80 })),
    bio: z.string().max(1000, t('validation.max', { count: 1000 })),
    location: z.string().max(80, t('validation.max', { count: 80 })),
    // Empty is valid; anything else must be a URL the browser can follow, which
    // is also what the server enforces before it lands in a public anchor.
    website_url: z
      .string()
      .trim()
      .max(200, t('validation.max', { count: 200 }))
      .refine((value) => value === '' || /^https?:\/\/\S+$/i.test(value), {
        message: t('validation.url'),
      }),
    preferred_language: z.enum(['fr', 'en']),
  })

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: user?.display_name || '',
      bio: user?.bio || '',
      location: user?.location || '',
      website_url: user?.website_url || '',
      preferred_language: user?.preferred_language || 'fr',
    },
  })

  const onSubmit = async (values) => {
    try {
      await updateProfile(values)
      // Keep the visible UI language in step with the saved preference.
      setLanguage(values.preferred_language)
      toast.success(t('account.profileSaved'))
    } catch (error) {
      const fields = apiFieldErrors(error)
      let matched = false
      Object.entries(fields).forEach(([key, message]) => {
        if (
          ['display_name', 'bio', 'location', 'website_url', 'preferred_language']
            .includes(key)
        ) {
          setError(key, { message })
          matched = true
        }
      })
      if (!matched) toast.error(apiErrorMessage(error))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="sv-card p-5" noValidate>
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <UserCircle className="size-4 text-brand-400" aria-hidden />
        {t('account.title')}
      </h2>

      <Field label={t('account.displayName')} error={errors.display_name?.message}>
        <input type="text" className="sv-input" {...register('display_name')} />
      </Field>

      <Field
        label={t('account.bio')}
        hint={t('account.bioHint')}
        error={errors.bio?.message}
      >
        <textarea rows={4} className="sv-input resize-y" {...register('bio')} />
      </Field>

      <Field label={t('account.location')} error={errors.location?.message}>
        <input
          type="text"
          className="sv-input"
          placeholder={t('account.locationPlaceholder')}
          {...register('location')}
        />
      </Field>

      <Field label={t('account.website')} error={errors.website_url?.message}>
        <input
          type="url"
          inputMode="url"
          className="sv-input"
          placeholder="https://exemple.com"
          {...register('website_url')}
        />
      </Field>

      <Field label={t('account.language')} error={errors.preferred_language?.message}>
        <select className="sv-input" {...register('preferred_language')}>
          <option value="fr">Francais</option>
          <option value="en">English</option>
        </select>
      </Field>

      <div className="mb-4 rounded-lg border border-ink-700 bg-ink-800 p-3 text-xs">
        <p className="mb-1 flex items-center gap-1.5 text-ink-400">
          <Link2 className="size-3.5" aria-hidden />
          {t('account.channelUrl')}
        </p>
        <code className="text-brand-300">
          {window.location.origin}/c/{user?.username}
        </code>
        <p className="mt-1 text-ink-500">
          {t('account.memberSince', {
            date: formatAbsolute(user?.created_at, i18n.language),
          })}
        </p>
      </div>

      <Button type="submit" loading={isSubmitting}>
        {t('common.save')}
      </Button>
    </form>
  )
}

function PasswordForm() {
  const { t } = useTranslation()

  const schema = z
    .object({
      current_password: z.string().min(1, t('validation.required')),
      new_password: z.string().min(8, t('validation.passwordMin')),
      confirm_password: z.string().min(1, t('validation.required')),
    })
    .refine((data) => data.new_password === data.confirm_password, {
      message: t('validation.passwordMismatch'),
      path: ['confirm_password'],
    })

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema) })

  const onSubmit = async ({ current_password, new_password }) => {
    try {
      await api.post('/accounts/me/password/', { current_password, new_password })
      toast.success(t('account.passwordChanged'))
      reset()
    } catch (error) {
      const fields = apiFieldErrors(error)
      if (fields.current_password) {
        setError('current_password', { message: fields.current_password })
      } else if (fields.new_password) {
        setError('new_password', { message: fields.new_password })
      } else {
        toast.error(apiErrorMessage(error))
      }
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="sv-card p-5" noValidate>
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <KeyRound className="size-4 text-brand-400" aria-hidden />
        {t('account.changePassword')}
      </h2>

      <Field label={t('account.currentPassword')} error={errors.current_password?.message} required>
        <input
          type="password"
          autoComplete="current-password"
          className="sv-input"
          {...register('current_password')}
        />
      </Field>

      <Field label={t('account.newPassword')} error={errors.new_password?.message} required>
        <input
          type="password"
          autoComplete="new-password"
          className="sv-input"
          {...register('new_password')}
        />
      </Field>

      <Field label={t('auth.passwordConfirm')} error={errors.confirm_password?.message} required>
        <input
          type="password"
          autoComplete="new-password"
          className="sv-input"
          {...register('confirm_password')}
        />
      </Field>

      <Button type="submit" loading={isSubmitting}>
        {t('common.save')}
      </Button>
    </form>
  )
}

/**
 * Signing out lives on this page rather than in the header. It is a rare,
 * one-way action, and a one-click icon next to the avatar is easy to hit by
 * accident when reaching for the profile link beside it.
 */
function SessionCard() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const handleLogout = () => {
    logout()
    toast.success(t('auth.loggedOut'))
    navigate('/')
  }

  return (
    <section className="sv-card p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <LogOut className="size-4 text-brand-400" aria-hidden />
        {t('account.session')}
      </h2>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar user={user} size="md" />
          <div>
            <p className="text-sm font-medium">{user?.display_name || user?.username}</p>
            <p className="text-xs text-ink-400">@{user?.username}</p>
          </div>
        </div>

        <Button variant="danger" onClick={handleLogout}>
          <LogOut className="size-4" />
          {t('nav.logout')}
        </Button>
      </div>

      <p className="mt-3 text-xs text-ink-500">{t('account.sessionHint')}</p>
    </section>
  )
}

export default function AccountPage() {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">{t('account.title')}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-400">
          <span>{user?.email}</span>
          <Badge tone={user?.role === 'admin' ? 'danger' : 'brand'}>
            {t(`roles.${user?.role}`)}
          </Badge>
        </div>
      </header>

      <div className="grid gap-5">
        <ProfileImagesCard />
        <ProfileForm />
        <PasswordForm />
        <SessionCard />
      </div>
    </div>
  )
}
