import { AlertTriangle, Check, CreditCard, Crown, Smartphone } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'

import CheckoutModal from '@/features/monetization/CheckoutModal'
import { Badge, Button, ErrorState, LoadingBlock } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatAbsolute } from '@/lib/format'
import {
  useCancelSubscription,
  useMySubscription,
  usePaymentProviders,
  usePlans,
} from '@/features/monetization/api'
import { useAuthStore } from '@/stores/useAuthStore'

export default function PlansPage() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)

  const plansQuery = usePlans()
  const providersQuery = usePaymentProviders()
  const subscriptionQuery = useMySubscription()
  const cancel = useCancelSubscription()

  const [checkoutPlan, setCheckoutPlan] = useState(null)

  if (plansQuery.isLoading) return <LoadingBlock />
  if (plansQuery.isError) {
    return <ErrorState error={plansQuery.error} onRetry={plansQuery.refetch} />
  }

  const plans = plansQuery.data ?? []
  const current = subscriptionQuery.data?.subscription
  const isAdFree = subscriptionQuery.data?.is_ad_free

  const doCancel = async () => {
    if (!window.confirm(t('billing.cancelConfirm'))) return
    try {
      await cancel.mutateAsync()
      toast.success(t('billing.cancelled'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-8 text-center">
        <h1 className="flex items-center justify-center gap-2 text-2xl font-bold sm:text-3xl">
          <Crown className="size-7 text-amber-400" aria-hidden />
          {t('billing.title')}
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-sm text-ink-400">
          {t('billing.subtitle')}
        </p>
      </header>

      {/* The sandbox banner is not decoration: a payment simulator that looks
          identical to a real one is how demo money becomes a support ticket. */}
      {providersQuery.data?.sandbox && (
        <p className="mb-6 flex items-start gap-2 rounded-card border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            <strong>{t('billing.sandboxTitle')}</strong> {t('billing.sandboxBody')}
          </span>
        </p>
      )}

      {current && current.is_currently_active && (
        <section className="mb-8 rounded-card border border-emerald-500/40 bg-emerald-500/10 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
                <Check className="size-4" aria-hidden />
                {t('billing.currentPlan', { plan: current.plan.name })}
              </p>
              <p className="mt-1 text-xs text-emerald-300/80">
                {current.auto_renew
                  ? t('billing.renewsOn', {
                      date: formatAbsolute(current.current_period_end, i18n.language),
                    })
                  : t('billing.endsOn', {
                      date: formatAbsolute(current.current_period_end, i18n.language),
                    })}
              </p>
            </div>
            {current.auto_renew && (
              <Button variant="secondary" size="sm" onClick={doCancel}
                      loading={cancel.isPending}>
                {t('billing.cancel')}
              </Button>
            )}
          </div>
          {!current.auto_renew && (
            <p className="mt-3 text-xs text-emerald-300/80">
              {t('billing.cancelledNotice')}
            </p>
          )}
        </section>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        {plans.map((plan) => {
          const isCurrent = current?.plan?.slug === plan.slug && current.is_currently_active
          return (
            <div
              key={plan.slug}
              className={cn(
                'flex flex-col rounded-card border p-6',
                isCurrent
                  ? 'border-emerald-500/50 bg-emerald-500/5'
                  : 'border-ink-800 bg-ink-850',
              )}
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <h2 className="text-lg font-semibold">{plan.name}</h2>
                {isCurrent && <Badge tone="success">{t('billing.active')}</Badge>}
              </div>

              <p className="mb-4 text-sm text-ink-400">{plan.description}</p>

              <p className="mb-1 text-3xl font-bold tabular-nums">
                {plan.price_display}
              </p>
              <p className="mb-5 text-xs text-ink-400">
                {t(`billing.period.${plan.billing_period}`)}
              </p>

              <ul className="mb-6 space-y-2 text-sm">
                {(plan.benefits ?? []).map((benefit) => (
                  <li key={benefit} className="flex items-start gap-2 text-ink-300">
                    <Check className="mt-0.5 size-4 shrink-0 text-emerald-400" aria-hidden />
                    {benefit}
                  </li>
                ))}
              </ul>

              <Button
                className="mt-auto w-full"
                disabled={isCurrent}
                onClick={() => {
                  if (!user) {
                    toast(t('billing.loginRequired'))
                    navigate('/login')
                    return
                  }
                  setCheckoutPlan(plan)
                }}
              >
                {isCurrent ? t('billing.active') : t('billing.subscribe')}
              </Button>
            </div>
          )
        })}
      </div>

      <section className="mt-8 rounded-card border border-ink-800 bg-ink-850 p-5">
        <h2 className="mb-3 text-sm font-semibold">{t('billing.paymentMethods')}</h2>
        <div className="flex flex-wrap gap-2">
          {(providersQuery.data?.providers ?? []).map((provider) => (
            <span
              key={provider.code}
              className="inline-flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800 px-3 py-2 text-sm"
            >
              {provider.kind === 'card' ? (
                <CreditCard className="size-4 text-brand-400" aria-hidden />
              ) : (
                <Smartphone className="size-4 text-brand-400" aria-hidden />
              )}
              {provider.label}
            </span>
          ))}
        </div>
        <p className="mt-3 text-xs text-ink-500">{t('billing.providerNote')}</p>
      </section>

      <CheckoutModal
        plan={checkoutPlan}
        open={Boolean(checkoutPlan)}
        onClose={() => setCheckoutPlan(null)}
        providers={providersQuery.data?.providers ?? []}
      />
    </div>
  )
}
