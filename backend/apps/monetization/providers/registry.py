"""Provider registry.

Every provider the UI offers is registered here. Today they are all backed by
`MockPaymentProvider`; going live with Orange Money means writing
`providers/orange_money.py` implementing `BasePaymentProvider` and changing one
line in this file. No view, serializer, task or template refers to a concrete
provider.
"""
from __future__ import annotations

from django.conf import settings

from apps.monetization.models import PaymentProvider
from apps.monetization.providers.base import BasePaymentProvider
from apps.monetization.providers.mock import MockPaymentProvider

# code -> (label, kind)
_PROVIDER_SPECS: dict[str, tuple[str, str]] = {
    PaymentProvider.ORANGE_MONEY: ("Orange Money", "mobile_money"),
    PaymentProvider.MOOV_MONEY: ("Moov Money", "mobile_money"),
    PaymentProvider.WAVE: ("Wave", "mobile_money"),
    PaymentProvider.CARD: ("Carte bancaire", "card"),
}


def _build_registry() -> dict[str, BasePaymentProvider]:
    """Instantiate the configured providers.

    `PAYMENTS_USE_MOCK` is the single switch. When it is turned off, this
    function is where the real implementations get wired in — and it will raise
    loudly for any provider that has none, rather than silently falling back to
    a simulator in production.
    """
    if settings.PAYMENTS_USE_MOCK:
        return {
            code: MockPaymentProvider(code=code, label=label, kind=kind)
            for code, (label, kind) in _PROVIDER_SPECS.items()
        }

    raise NotImplementedError(
        "PAYMENTS_USE_MOCK is disabled but no real payment provider is "
        "implemented yet. Phase 7 replaces the mock behind this same interface; "
        "until then the platform must not pretend to take real money."
    )


_registry: dict[str, BasePaymentProvider] | None = None


def get_registry() -> dict[str, BasePaymentProvider]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_provider(code: str) -> BasePaymentProvider:
    registry = get_registry()
    if code not in registry:
        raise KeyError(f"Fournisseur de paiement inconnu: {code}")
    return registry[code]


def available_providers() -> list[dict]:
    """Checkout options, in the order the UI should show them."""
    return [provider.describe() for provider in get_registry().values()
            if provider.enabled]


def reset_registry() -> None:
    """Test hook — forces re-instantiation after settings change."""
    global _registry
    _registry = None
