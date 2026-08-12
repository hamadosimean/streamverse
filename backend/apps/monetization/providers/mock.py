"""Mock payment provider — a real async simulation, not a success stub.

The point of a mock is to exercise the code that will run in production. A stub
that flips a transaction to `completed` inside the request proves nothing: the
hard parts of payments are *asynchronous confirmation*, *signature
verification*, *replay* and *out-of-order delivery*, and a synchronous stub
tests none of them.

So this mock:

* returns immediately with a `pending` transaction, exactly like a real
  mobile-money push that the user must confirm on their handset;
* schedules a Celery task that calls **our own public webhook endpoint** after a
  realistic delay, over HTTP, with an HMAC signature;
* signs with the same scheme the webhook verifier checks, so a signature bug
  fails here rather than in production;
* deliberately fails a configurable share of payments, and can be told to fail a
  specific one, so the failure path is exercised too;
* sends the same event twice when asked, so the replay guard is tested.

Swapping in Orange Money or Wave means implementing `BasePaymentProvider` and
changing a setting. Nothing outside `providers/` knows which one is live.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

from django.conf import settings

from apps.monetization.providers.base import (
    BasePaymentProvider,
    InitiationResult,
    PaymentError,
    SignatureError,
    WebhookResult,
)

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Streamverse-Signature"
TIMESTAMP_HEADER = "X-Streamverse-Timestamp"


def sign_payload(body: bytes, timestamp: str, secret: str | None = None) -> str:
    """`v1=<hex>` over `timestamp.body`.

    The timestamp is inside the signed material on purpose: signing the body
    alone lets an attacker who once captured a valid callback replay it forever.
    """
    secret = secret or settings.MOCK_PAYMENT_WEBHOOK_SECRET
    message = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_signature(body: bytes, signature: str, timestamp: str,
                     secret: str | None = None,
                     tolerance_seconds: int = 300) -> None:
    """Raise `SignatureError` unless the signature is valid and fresh."""
    if not signature or not timestamp:
        raise SignatureError("Signature ou horodatage manquant.")

    try:
        age = abs(time.time() - float(timestamp))
    except (TypeError, ValueError) as exc:
        raise SignatureError("Horodatage illisible.") from exc

    if age > tolerance_seconds:
        raise SignatureError(f"Horodatage hors tolerance ({age:.0f}s).")

    expected = sign_payload(body, timestamp, secret)
    # Constant-time: a plain == leaks the signature prefix through timing.
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("Signature invalide.")


class MockPaymentProvider(BasePaymentProvider):
    """Simulates one real provider. One instance per `code`."""

    def __init__(self, code: str, label: str, kind: str = "mobile_money"):
        self.code = code
        self.label = label
        self.kind = kind

    def initiate(self, *, transaction, payer_identifier: str,
                 return_url: str = "") -> InitiationResult:
        from apps.monetization.tasks import deliver_mock_webhook

        if self.kind == "mobile_money" and not payer_identifier:
            raise PaymentError("Numero de telephone requis pour le mobile money.")

        reference = f"{self.code.upper()}-{secrets.token_hex(8)}"

        # A real push notification lands on the payer's handset a second or two
        # later; the confirmation arrives whenever they get round to it.
        delay = settings.MOCK_PAYMENT_CONFIRM_DELAY_SECONDS
        deliver_mock_webhook.apply_async(
            args=[str(transaction.pk), reference], countdown=delay
        )

        instructions = (
            f"Confirmez le paiement de {transaction.amount} FCFA sur votre "
            f"telephone ({payer_identifier})."
            if self.kind == "mobile_money"
            else f"Validez le paiement de {transaction.amount} FCFA "
                 f"aupres de votre banque."
        )

        logger.info("mock payment initiated: %s ref=%s amount=%s delay=%ss",
                    self.code, reference, transaction.amount, delay)

        return InitiationResult(
            provider_reference=reference,
            redirect_url=None,
            instructions=instructions,
            raw={"provider": self.code, "reference": reference,
                 "simulated_delay_seconds": delay},
        )

    def verify_webhook(self, *, headers: dict, body: bytes) -> WebhookResult:
        # Header lookup is case-insensitive: Django normalises to HTTP_X_...,
        # and proxies may change case in transit.
        normalised = {k.lower().replace("_", "-"): v for k, v in headers.items()}
        signature = normalised.get(SIGNATURE_HEADER.lower(), "")
        timestamp = normalised.get(TIMESTAMP_HEADER.lower(), "")

        verify_signature(body, signature, timestamp)

        try:
            payload = json.loads(body.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureError("Corps de webhook illisible.") from exc

        return WebhookResult(
            event_id=payload.get("event_id", ""),
            event_type=payload.get("event_type", ""),
            provider_reference=payload.get("reference", ""),
            outcome=payload.get("status", "pending"),
            amount=payload.get("amount"),
            failure_reason=payload.get("failure_reason", ""),
            raw=payload,
        )
