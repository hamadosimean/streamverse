import { CheckCircle2, CreditCard, Loader2, Smartphone, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'

import { Button, Field, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import {
  billingKeys,
  useCheckout,
  useTransactionStatus,
} from '@/features/monetization/api'

/**
 * Subscription checkout.
 *
 * Three states, mirroring how the payment actually works: choose a method,
 * **wait for the provider to confirm**, then see the outcome. The waiting state
 * is not padding — a mobile-money push has to be approved on the payer's
 * handset, and pretending the payment is instant would be a lie the user finds
 * out about when their subscription does not appear.
 */
export default function CheckoutModal({ plan, open, onClose, providers }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const checkout = useCheckout()

  const [provider, setProvider] = useState('')
  const [payerIdentifier, setPayerIdentifier] = useState('')
  const [transactionId, setTransactionId] = useState(null)

  const { data: transaction } = useTransactionStatus(transactionId, {
    enabled: Boolean(transactionId),
  })

  useEffect(() => {
    if (open) {
      setProvider(providers?.[0]?.code ?? '')
      setPayerIdentifier('')
      setTransactionId(null)
    }
  }, [open, providers])

  useEffect(() => {
    if (transaction?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: billingKeys.subscription })
    }
  }, [transaction?.status, queryClient])

  const selected = providers?.find((p) => p.code === provider)
  const needsPhone = selected && selected.kind !== 'card'

  const submit = async () => {
    try {
      const created = await checkout.mutateAsync({
        plan_slug: plan.slug,
        provider,
        payer_identifier: payerIdentifier,
      })
      setTransactionId(created.id)
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const settled = transaction && transaction.status !== 'pending'
  const succeeded = transaction?.status === 'completed'

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={plan ? t('billing.checkoutTitle', { plan: plan.name }) : ''}
      footer={
        settled ? (
          <Button onClick={onClose}>{t('common.close')}</Button>
        ) : transactionId ? null : (
          <>
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={submit}
              loading={checkout.isPending}
              disabled={!provider || (needsPhone && !payerIdentifier.trim())}
            >
              {t('billing.pay', { amount: plan?.price_display })}
            </Button>
          </>
        )
      }
    >
      {/* ---------------------------------------------------- choose method */}
      {!transactionId && (
        <>
          <Field label={t('billing.choosePaymentMethod')} required>
            <div className="space-y-2">
              {(providers ?? []).map((option) => (
                <label
                  key={option.code}
                  className={cn(
                    'flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm transition',
                    provider === option.code
                      ? 'border-brand-500 bg-brand-500/10'
                      : 'border-ink-700 hover:border-ink-600',
                  )}
                >
                  <input
                    type="radio"
                    name="provider"
                    value={option.code}
                    checked={provider === option.code}
                    onChange={(event) => setProvider(event.target.value)}
                    className="accent-brand-500"
                  />
                  {option.kind === 'card' ? (
                    <CreditCard className="size-4 text-brand-400" aria-hidden />
                  ) : (
                    <Smartphone className="size-4 text-brand-400" aria-hidden />
                  )}
                  {option.label}
                </label>
              ))}
            </div>
          </Field>

          <Field
            label={needsPhone ? t('billing.phoneNumber') : t('billing.cardLast4')}
            hint={needsPhone ? t('billing.phoneHint') : t('billing.cardHint')}
            required={needsPhone}
          >
            <input
              type="text"
              className="sv-input"
              maxLength={64}
              inputMode={needsPhone ? 'tel' : 'numeric'}
              placeholder={needsPhone ? '+226 70 00 00 00' : '4242'}
              value={payerIdentifier}
              onChange={(event) => setPayerIdentifier(event.target.value)}
            />
          </Field>

          <p className="rounded-lg border border-ink-700 bg-ink-800 p-3 text-xs text-ink-400">
            {t('billing.checkoutNotice')}
          </p>
        </>
      )}

      {/* -------------------------------------------------------- awaiting */}
      {transactionId && !settled && (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <Loader2 className="size-10 animate-spin text-brand-400" aria-hidden />
          <p className="text-sm font-medium">{t('billing.awaitingConfirmation')}</p>
          <p className="max-w-sm text-xs text-ink-400">
            {needsPhone
              ? t('billing.awaitingMobileMoney', { phone: payerIdentifier })
              : t('billing.awaitingCard')}
          </p>
        </div>
      )}

      {/* --------------------------------------------------------- outcome */}
      {settled && (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          {succeeded ? (
            <>
              <CheckCircle2 className="size-12 text-emerald-400" aria-hidden />
              <p className="text-sm font-semibold text-emerald-300">
                {t('billing.paymentSucceeded')}
              </p>
              <p className="text-xs text-ink-400">{t('billing.subscriptionActive')}</p>
            </>
          ) : (
            <>
              <XCircle className="size-12 text-red-400" aria-hidden />
              <p className="text-sm font-semibold text-red-300">
                {t('billing.paymentFailed')}
              </p>
              <p className="max-w-sm text-xs text-ink-400">
                {transaction.failure_reason || t('billing.paymentFailedHint')}
              </p>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
