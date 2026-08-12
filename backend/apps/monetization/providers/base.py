"""Payment provider interface.

One interface for mobile money (Orange Money, Moov Money, Wave) **and** cards.
They differ enormously in their APIs but share the same shape from the
application's point of view:

    initiate  -> "I have asked for this money; here is how the user completes it"
    (later)   -> the provider calls our webhook to say what happened
    verify    -> "is this callback really from you?"

Everything else — polling, retries, reconciliation — is built on those three.
Swapping the mock for a real provider means implementing this class and changing
one setting; no call site outside `providers/` knows which provider is active.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class InitiationResult:
    """What the application needs after asking a provider for money."""

    provider_reference: str
    # Where to send the user, if the provider needs them to act (card 3-D Secure
    # page, Wave checkout, USSD prompt confirmation screen).
    redirect_url: str | None = None
    # Human-readable next step, shown while the payment is pending.
    instructions: str = ""
    # Everything the provider returned, stored verbatim for reconciliation.
    raw: dict = field(default_factory=dict)


@dataclass
class WebhookResult:
    """A verified, parsed provider callback."""

    event_id: str
    event_type: str
    provider_reference: str
    # One of: completed | failed | cancelled | pending
    outcome: str
    amount: int | None = None
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentError(Exception):
    """Provider refused the request outright (bad number, closed account…)."""


class SignatureError(Exception):
    """Callback did not authenticate. Never process the payload after this."""


class BasePaymentProvider(abc.ABC):
    #: Value stored in `Transaction.provider`.
    code: str = ""
    #: Human label shown in the checkout UI.
    label: str = ""
    #: `mobile_money` | `card`. Drives which fields the checkout form asks for.
    kind: str = "mobile_money"
    #: Whether this provider is safe to offer in the UI right now.
    enabled: bool = True

    @abc.abstractmethod
    def initiate(self, *, transaction, payer_identifier: str,
                 return_url: str = "") -> InitiationResult:
        """Ask the provider to collect `transaction.amount` from the payer.

        Must be idempotent with respect to `transaction.idempotency_key`:
        calling it twice for the same key must not create two charges.
        """

    @abc.abstractmethod
    def verify_webhook(self, *, headers: dict, body: bytes) -> WebhookResult:
        """Authenticate and parse an inbound callback.

        Raise `SignatureError` if authentication fails. Callers must not look at
        the payload before this returns.
        """

    def describe(self) -> dict:
        """What the checkout UI needs to render this option."""
        return {
            "code": self.code,
            "label": self.label,
            "kind": self.kind,
            "enabled": self.enabled,
        }
