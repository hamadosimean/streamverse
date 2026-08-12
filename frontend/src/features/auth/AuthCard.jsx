import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Logo from '@/components/Logo'

/** Shared shell for the auth screens, so they stay visually identical. */
export default function AuthCard({ title, subtitle, children, footer }) {
  const { t } = useTranslation()

  return (
    <div className="mx-auto flex max-w-md flex-col justify-center py-10">
      <Link to="/" className="mb-6 flex items-center justify-center gap-2">
        <Logo size={44} />
        <span className="text-xl font-bold">{t('app.name')}</span>
      </Link>

      <div className="sv-card p-6">
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 mb-5 text-sm text-ink-400">{subtitle}</p>}
        {children}
      </div>

      {footer && <div className="mt-4 text-center text-sm text-ink-400">{footer}</div>}
    </div>
  )
}
