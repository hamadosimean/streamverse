"""Payment posting logic — the single place money changes state.

Two invariants, both enforced by the database rather than by careful coding:

1. **One transaction per idempotency key.** A double-clicked button, a retried
   request and a client that lost the response all converge on the same row.
2. **One effect per webhook event.** Providers retry callbacks until they get a
   2xx, so the same event arrives repeatedly; `WebhookEvent` has a unique
   constraint on (provider, event_id) and processing is skipped on conflict.

Nothing here trusts the client for an amount: the price is read from the plan
server-side. A checkout request that says "1 FCFA" gets charged the real price.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.monetization.models import (
    SubscriptionPlan,
    SubscriptionStatus,
    Transaction,
    TransactionStatus,
    TransactionType,
    UserSubscription,
    WebhookEvent,
)
from apps.monetization.providers.base import PaymentError
from apps.monetization.providers.registry import get_provider

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    pass


def build_idempotency_key(user_id, plan_id, kind: str = "sub") -> str:
    """A fresh key per deliberate checkout attempt.

    Deliberately *not* derived from (user, plan) alone: a user whose first
    payment genuinely failed must be able to try again, and a key that collides
    with the failed attempt would block them forever.
    """
    return f"{kind}-{user_id}-{plan_id}-{secrets.token_hex(8)}"


@db_transaction.atomic
def start_subscription_checkout(*, user, plan: SubscriptionPlan, provider_code: str,
                                payer_identifier: str = "",
                                idempotency_key: str | None = None,
                                request=None) -> Transaction:
    """Create a pending subscription + transaction and ask the provider for money.

    Returns immediately with a `pending` transaction. Activation happens when the
    provider's webhook arrives — never here, because a provider that has not
    confirmed has not paid.
    """
    if not plan.is_active:
        raise CheckoutError("Cette formule n'est plus disponible.")

    key = idempotency_key or build_idempotency_key(user.pk, plan.pk)

    # Idempotency is checked FIRST, before the "already subscribed" guard.
    # Ordering matters: a client retrying after a lost response sends the same
    # key, and by then its own pending subscription exists — so guarding first
    # would reject the retry with "a payment is already in progress" instead of
    # returning the transaction it is asking about.
    already = Transaction.objects.filter(idempotency_key=key).first()
    if already is not None:
        logger.info("checkout: idempotent replay for key=%s -> %s", key, already.pk)
        return already

    existing = UserSubscription.objects.select_for_update().filter(
        user=user, status__in=[SubscriptionStatus.PENDING, SubscriptionStatus.ACTIVE]
    ).first()
    if existing is not None:
        if existing.status == SubscriptionStatus.ACTIVE:
            raise CheckoutError("Vous avez deja un abonnement actif.")
        raise CheckoutError(
            "Un paiement est deja en cours pour votre abonnement. "
            "Attendez sa confirmation ou annulez-le."
        )

    subscription = UserSubscription.objects.create(
        user=user, plan=plan, status=SubscriptionStatus.PENDING, auto_renew=True
    )

    try:
        payment = Transaction.objects.create(
            user=user,
            subscription=subscription,
            plan=plan,
            provider=provider_code,
            type=TransactionType.SUBSCRIPTION,
            status=TransactionStatus.PENDING,
            # Price comes from the plan, never from the request body.
            amount=plan.price,
            idempotency_key=key,
            payer_identifier=payer_identifier[:64],
        )
    except IntegrityError:
        # Lost a race on the unique key: the winner's row is the truth.
        existing_txn = Transaction.objects.get(idempotency_key=key)
        logger.info("checkout: idempotency race resolved to %s", existing_txn.pk)
        return existing_txn

    provider = get_provider(provider_code)
    try:
        result = provider.initiate(transaction=payment,
                                   payer_identifier=payer_identifier)
    except PaymentError as exc:
        payment.status = TransactionStatus.FAILED
        payment.failure_reason = str(exc)
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = timezone.now()
        subscription.save(update_fields=["status", "cancelled_at", "updated_at"])
        raise CheckoutError(str(exc)) from exc

    payment.provider_reference = result.provider_reference
    payment.provider_payload = result.raw
    payment.save(update_fields=["provider_reference", "provider_payload", "updated_at"])

    audit.record(
        AuditAction.PAYMENT_EVENT, actor=user, target=payment,
        metadata={"event": "checkout_started", "provider": provider_code,
                  "amount": payment.amount, "plan": plan.slug},
        request=request,
    )

    logger.info("checkout started: user=%s plan=%s amount=%s provider=%s txn=%s",
                user.pk, plan.slug, payment.amount, provider_code, payment.pk)
    return payment


def _activate_subscription(subscription: UserSubscription) -> None:
    """Start or extend the paid period.

    Extends from the *current* period end when one exists, so renewing early
    never costs the subscriber the days they already paid for.
    """
    now = timezone.now()
    base = (
        subscription.current_period_end
        if subscription.current_period_end and subscription.current_period_end > now
        else now
    )

    subscription.status = SubscriptionStatus.ACTIVE
    subscription.started_at = subscription.started_at or now
    subscription.current_period_end = base + timedelta(days=subscription.plan.period_days)
    subscription.renewal_failures = 0
    subscription.save(update_fields=["status", "started_at", "current_period_end",
                                     "renewal_failures", "updated_at"])


def apply_webhook_outcome(event: WebhookEvent) -> str:
    """Act on a verified callback. Idempotent by construction.

    Returns a short description of what happened, for logging and tests.
    """
    payment = event.transaction
    if payment is None:
        return "no_matching_transaction"

    outcome = (event.payload or {}).get("status", "pending")

    with db_transaction.atomic():
        payment = Transaction.objects.select_for_update().get(pk=payment.pk)

        # Terminal states are final. A late "failed" after a "completed" must not
        # revoke a subscription the user already paid for.
        if payment.status in (TransactionStatus.COMPLETED, TransactionStatus.FAILED):
            return f"already_{payment.status}"

        amount = (event.payload or {}).get("amount")
        if outcome == "completed" and amount is not None and int(amount) != payment.amount:
            # A provider confirming a different amount than we asked for is a
            # reconciliation problem, not a subscription to activate.
            payment.status = TransactionStatus.FAILED
            payment.failure_reason = (
                f"Montant confirme ({amount}) different du montant attendu "
                f"({payment.amount})."
            )
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            logger.error("payment %s amount mismatch: %s != %s",
                         payment.pk, amount, payment.amount)
            return "amount_mismatch"

        if outcome == "completed":
            payment.status = TransactionStatus.COMPLETED
            payment.completed_at = timezone.now()
            payment.save(update_fields=["status", "completed_at", "updated_at"])

            if payment.subscription is not None:
                subscription = UserSubscription.objects.select_for_update().get(
                    pk=payment.subscription_id
                )
                _activate_subscription(subscription)
            result = "completed"

        elif outcome in ("failed", "cancelled"):
            payment.status = (TransactionStatus.CANCELLED if outcome == "cancelled"
                              else TransactionStatus.FAILED)
            payment.failure_reason = (event.payload or {}).get("failure_reason", "")
            payment.save(update_fields=["status", "failure_reason", "updated_at"])

            subscription = payment.subscription
            if subscription and subscription.status == SubscriptionStatus.PENDING:
                subscription.status = SubscriptionStatus.CANCELLED
                subscription.cancelled_at = timezone.now()
                subscription.save(update_fields=["status", "cancelled_at", "updated_at"])
            result = outcome

        else:
            return "pending_noop"

    audit.record(
        AuditAction.PAYMENT_EVENT, actor=payment.user, target=payment,
        metadata={"event": f"payment_{result}", "provider": payment.provider,
                  "amount": payment.amount, "event_id": event.event_id},
    )
    logger.info("payment %s -> %s (event %s)", payment.pk, result, event.event_id)
    return result


def cancel_subscription(subscription: UserSubscription, *, request=None) -> UserSubscription:
    """Stop auto-renewal, keeping access until the paid period ends.

    Deliberately not an immediate revocation: the subscriber paid for the period,
    and cutting them off early would be taking money for nothing.
    """
    subscription.auto_renew = False
    subscription.cancelled_at = timezone.now()

    if subscription.status == SubscriptionStatus.PENDING:
        # Nothing was ever paid, so there is no period to honour.
        subscription.status = SubscriptionStatus.CANCELLED

    subscription.save(update_fields=["auto_renew", "cancelled_at", "status",
                                     "updated_at"])

    audit.record(
        AuditAction.PAYMENT_EVENT, actor=subscription.user, target=subscription,
        metadata={"event": "subscription_cancelled", "plan": subscription.plan.slug,
                  "access_until": subscription.current_period_end.isoformat()
                  if subscription.current_period_end else None},
        request=request,
    )
    return subscription
