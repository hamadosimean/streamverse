import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

/** Shared shell for the auth screens, so they stay visually identical. */
export default function AuthCard({ title, subtitle, children, footer }) {
  const { t } = useTranslation()

  return (
    <div className="mx-auto flex max-w-md flex-col justify-center py-10">
      <Link to="/" className="mb-6 flex items-center justify-center gap-2">
        <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-accent-500">
          <svg viewBox="0 0 24 24" className="size-5 fill-white" aria-hidden>
            <path d="M8 5l11 7-11 7z" />
          </svg>
        </span>
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
