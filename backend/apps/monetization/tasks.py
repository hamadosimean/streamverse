"""Monetization background work.

The mock provider's webhook delivery lives here rather than in the request
cycle, because that is the whole point: a real provider confirms asynchronously,
over HTTP, minutes later, sometimes twice, sometimes never.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.monetization.models import (
    SubscriptionStatus,
    Transaction,
    TransactionStatus,
    TransactionType,
    UserSubscription,
)
from apps.monetization.providers.mock import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_payload,
)

logger = logging.getLogger(__name__)


@shared_task(name="monetization.deliver_mock_webhook", bind=True, max_retries=3)
def deliver_mock_webhook(self, transaction_id: str, reference: str,
                         force_outcome: str | None = None,
                         duplicate: bool = False) -> dict:
    """Call our own webhook endpoint the way a real provider would.

    Over HTTP, signed, from outside the request that started the payment. That
    means the production code path — signature verification, replay guard,
    transaction state machine — is the one being exercised, not a shortcut.
    """
    payment = Transaction.objects.filter(pk=transaction_id).first()
    if payment is None:
        return {"status": "missing_transaction"}

    if payment.status != TransactionStatus.PENDING:
        return {"status": "already_settled", "state": payment.status}

    outcome = force_outcome
    if outcome is None:
        # A configurable share of payments fail, so the failure path is exercised
        # by the demo rather than only by a hand-written test.
        outcome = ("failed"
                   if secrets.randbelow(100) < settings.MOCK_PAYMENT_FAILURE_PERCENT
                   else "completed")

    payload = {
        "event_id": f"evt_{secrets.token_hex(12)}",
        "event_type": f"payment.{outcome}",
        "reference": reference,
        "status": outcome,
        "amount": payment.amount,
        "currency": payment.currency,
        "provider": payment.provider,
        "failure_reason": ("Solde insuffisant (simulation)."
                           if outcome == "failed" else ""),
    }

    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_payload(body, timestamp),
        TIMESTAMP_HEADER: timestamp,
    }

    url = f"{settings.INTERNAL_API_BASE_URL}/api/monetization/webhooks/{payment.provider}/"

    try:
        response = requests.post(url, data=body, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("mock webhook delivery failed for %s: %s", transaction_id, exc)
        raise self.retry(countdown=15 * (self.request.retries + 1)) from exc

    logger.info("mock webhook delivered: txn=%s outcome=%s http=%s",
                transaction_id, outcome, response.status_code)

    if duplicate:
        # Deliberately redeliver the identical event: real providers do this, and
        # the replay guard needs to be exercised, not assumed.
        requests.post(url, data=body, headers=headers, timeout=10)
        logger.info("mock webhook redelivered (replay test) for %s", transaction_id)

    return {"status": "delivered", "outcome": outcome,
            "event_id": payload["event_id"]}


@shared_task(name="monetization.process_renewals")
def process_renewals() -> dict:
    """Charge subscriptions whose period is ending.

    Creates a *new* pending transaction and lets the provider confirm it, exactly
    like a first payment. A renewal that silently extends access without a
    confirmed payment would be giving the product away.
    """
    from apps.monetization.services.payments import build_idempotency_key
    from apps.monetization.providers.registry import get_provider

    window_end = timezone.now() + timedelta(hours=settings.RENEWAL_LEAD_HOURS)
    due = UserSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        auto_renew=True,
        current_period_end__lte=window_end,
    ).select_related("plan", "user")

    started = 0
    for subscription in due:
        # Skip if a renewal attempt is already in flight for this period.
        pending = subscription.transactions.filter(
            status=TransactionStatus.PENDING, type=TransactionType.RENEWAL
        ).exists()
        if pending:
            continue

        last = subscription.transactions.filter(
            status=TransactionStatus.COMPLETED
        ).order_by("-created_at").first()
        provider_code = last.provider if last else "orange_money"

        # Key is scoped to the period being renewed, so a beat task that runs
        # twice in the same window cannot charge twice.
        period_stamp = subscription.current_period_end.strftime("%Y%m%d%H")
        key = f"renew-{subscription.pk}-{period_stamp}"

        if Transaction.objects.filter(idempotency_key=key).exists():
            continue

        payment = Transaction.objects.create(
            user=subscription.user,
            subscription=subscription,
            plan=subscription.plan,
            provider=provider_code,
            type=TransactionType.RENEWAL,
            status=TransactionStatus.PENDING,
            amount=subscription.plan.price,
            idempotency_key=key,
            payer_identifier=last.payer_identifier if last else "",
        )

        try:
            result = get_provider(provider_code).initiate(
                transaction=payment,
                payer_identifier=payment.payer_identifier or "renewal",
            )
            payment.provider_reference = result.provider_reference
            payment.provider_payload = result.raw
            payment.save(update_fields=["provider_reference", "provider_payload",
                                        "updated_at"])
            started += 1
        except Exception as exc:
            payment.status = TransactionStatus.FAILED
            payment.failure_reason = str(exc)[:2000]
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            logger.warning("renewal initiation failed for %s: %s", subscription.pk, exc)

    if started:
        logger.info("renewals: %d payment(s) initiated", started)
    return {"due": due.count(), "initiated": started}


@shared_task(name="monetization.expire_subscriptions")
def expire_subscriptions() -> dict:
    """Mark lapsed subscriptions expired.

    Benefits already stop at `current_period_end` because every check uses
    `active()`; this makes the state visible rather than leaving rows that look
    active but grant nothing.
    """
    now = timezone.now()
    expired = UserSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE, current_period_end__lt=now
    ).update(status=SubscriptionStatus.EXPIRED)

    if expired:
        logger.info("subscriptions: %d expired", expired)
    return {"expired": expired}


@shared_task(name="monetization.expire_campaigns")
def expire_campaigns() -> dict:
    from apps.monetization.services.ads import expire_finished_campaigns

    return {"ended": expire_finished_campaigns()}


@shared_task(name="monetization.aggregate_ad_stats")
def aggregate_ad_stats() -> dict:
    """Reconcile campaign counters against the impression rows.

    Same reasoning as the engagement counters: the denormalised values are a
    cache written on a hot path, and a crash between the row insert and the
    counter update would otherwise leave them permanently wrong.
    """
    from apps.monetization.models import AdCampaign

    campaigns = AdCampaign.objects.annotate(
        real_impressions=Count("impressions", distinct=True),
        real_completed=Count("impressions", filter=Q(impressions__completed=True),
                             distinct=True),
        real_clicks=Count("impressions", filter=Q(impressions__clicked=True),
                          distinct=True),
    )

    corrected = 0
    for campaign in campaigns:
        changes = {}
        if campaign.impression_count != campaign.real_impressions:
            changes["impression_count"] = campaign.real_impressions
        if campaign.completed_count != campaign.real_completed:
            changes["completed_count"] = campaign.real_completed
        if campaign.click_count != campaign.real_clicks:
            changes["click_count"] = campaign.real_clicks
        if changes:
            AdCampaign.objects.filter(pk=campaign.pk).update(**changes)
            corrected += 1

    return {"scanned": len(campaigns), "corrected": corrected}


@shared_task(name="monetization.sweep_stale_payments")
def sweep_stale_payments(timeout_minutes: int | None = None) -> dict:
    """Fail payments the provider never confirmed.

    A mobile-money push the payer ignores produces no callback at all. Without
    this, the subscription sits `pending` forever and the user can never retry,
    because the open-subscription constraint blocks a second checkout.
    """
    timeout_minutes = timeout_minutes or settings.PAYMENT_PENDING_TIMEOUT_MINUTES
    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)

    stale = Transaction.objects.filter(
        status=TransactionStatus.PENDING, created_at__lt=cutoff
    ).select_related("subscription")

    count = 0
    for payment in stale:
        payment.status = TransactionStatus.FAILED
        payment.failure_reason = (
            f"Aucune confirmation du fournisseur apres {timeout_minutes} minutes."
        )
        payment.save(update_fields=["status", "failure_reason", "updated_at"])

        subscription = payment.subscription
        if subscription and subscription.status == SubscriptionStatus.PENDING:
            subscription.status = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = timezone.now()
            subscription.save(update_fields=["status", "cancelled_at", "updated_at"])
        count += 1

    if count:
        logger.info("payments: %d stale pending payment(s) failed", count)
    return {"failed": count}


@shared_task(name="monetization.revenue_snapshot")
def revenue_snapshot() -> dict:
    """Pre-aggregate revenue for the admin dashboard into Redis."""
    from django.core.cache import cache

    since = timezone.now() - timedelta(days=30)
    totals = Transaction.objects.filter(
        status=TransactionStatus.COMPLETED, completed_at__gte=since
    ).aggregate(revenue=Sum("amount"), count=Count("id"))

    snapshot = {
        "revenue_fcfa": totals["revenue"] or 0,
        "transactions": totals["count"] or 0,
        "active_subscriptions": UserSubscription.objects.active().count(),
        "generated_at": timezone.now().isoformat(),
    }
    cache.set("monetization:revenue_snapshot", snapshot, 3600)
    return snapshot
