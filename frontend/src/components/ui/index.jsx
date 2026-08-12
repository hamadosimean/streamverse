import { AlertTriangle, Loader2, X } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/cn'

/* ------------------------------------------------------------------ Button */
const BUTTON_VARIANTS = {
  primary: 'bg-brand-600 hover:bg-brand-500 text-white shadow-sm',
  secondary: 'bg-ink-800 hover:bg-ink-700 text-ink-100 border border-ink-700',
  ghost: 'hover:bg-ink-800 text-ink-300 hover:text-ink-100',
  danger: 'bg-red-600 hover:bg-red-500 text-white',
  outline: 'border border-brand-500 text-brand-300 hover:bg-brand-500/10',
}

const BUTTON_SIZES = {
  sm: 'px-3 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-5 py-2.5 text-base gap-2',
  icon: 'p-2',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...props
}) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium transition',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------- Field */
export function Field({ label, error, hint, required, children, className }) {
  return (
    <div className={cn('mb-4', className)}>
      {label && (
        <label className="sv-label">
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
      )}
      {children}
      {hint && !error && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------- Badge */
const BADGE_TONES = {
  neutral: 'bg-ink-700 text-ink-200',
  brand: 'bg-brand-500/15 text-brand-300 border border-brand-500/30',
  success: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
  danger: 'bg-red-500/15 text-red-300 border border-red-500/30',
}

export function Badge({ tone = 'neutral', className, children }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

/* ----------------------------------------------------------------- Spinner */
export function Spinner({ className }) {
  return <Loader2 className={cn('size-5 animate-spin text-brand-400', className)} />
}

export function LoadingBlock({ label }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-ink-400">
      <Spinner className="size-7" />
      <p className="text-sm">{label ?? t('common.loading')}</p>
    </div>
  )
}

/* -------------------------------------------------------------- ProgressBar */
export function ProgressBar({ value = 0, className, tone = 'brand' }) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0))
  const fill = {
    brand: 'bg-gradient-to-r from-brand-500 to-accent-500',
    success: 'bg-emerald-500',
    danger: 'bg-red-500',
  }[tone]

  return (
    <div
      className={cn('h-2 w-full overflow-hidden rounded-full bg-ink-700', className)}
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-300', fill)}
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}

/* ------------------------------------------------------------ Empty / Error */
export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-card',
        'border border-dashed border-ink-700 px-6 py-14 text-center',
        className,
      )}
    >
      {Icon && <Icon className="size-10 text-ink-600" aria-hidden />}
      <h3 className="text-base font-semibold text-ink-100">{title}</h3>
      {description && <p className="max-w-md text-sm text-ink-400">{description}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }) {
  const { t } = useTranslation()
  const message =
    error?.response?.data?.detail || error?.message || t('common.errorRetry')

  return (
    <div
      className={cn(
        'flex flex-col items-center gap-3 rounded-card border border-red-500/30',
        'bg-red-500/5 px-6 py-10 text-center',
        className,
      )}
    >
      <AlertTriangle className="size-8 text-red-400" aria-hidden />
      <p className="text-sm text-red-200">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------- Modal */
export function Modal({ open, onClose, title, children, footer }) {
  const { t } = useTranslation()

  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => event.key === 'Escape' && onClose?.()
    document.addEventListener('keydown', onKey)
    // Prevent the page behind the dialog from scrolling under it.
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}
    >
      <div className="sv-card w-full max-w-lg p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="rounded p-1 text-ink-400 transition hover:bg-ink-800 hover:text-ink-100"
          >
            <X className="size-5" />
          </button>
        </div>
        <div className="text-sm text-ink-300">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- Skeleton */
export function SkeletonCard() {
  return (
    <div className="space-y-2">
      <div className="sv-skeleton aspect-video w-full" />
      <div className="sv-skeleton h-4 w-4/5" />
      <div className="sv-skeleton h-3 w-2/5" />
    </div>
  )
}

export function SkeletonGrid({ count = 8 }) {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }, (_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  )
}
