"""Monetization: ad campaigns, subscription plans, and payments.

**Money is always an integer number of FCFA.** The XOF franc has no minor unit,
so there is nothing to round — but the reason for integers is the general one:
floats silently lose cents, and a payment ledger that disagrees with the
provider by a rounding error is worse than one that fails loudly.

**Every payment-initiating path carries a DB-unique idempotency key.** A retried
request, a double-clicked button and a replayed webhook must all converge on one
row. That is enforced by the database, not by application checks that race.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.files.storage import storages
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


# ==========================================================================
# Subscriptions
# ==========================================================================
class BillingPeriod(models.TextChoices):
    MONTHLY = "monthly", _("Mensuel")
    QUARTERLY = "quarterly", _("Trimestriel")
    YEARLY = "yearly", _("Annuel")

    @staticmethod
    def days(period: str) -> int:
        return {"monthly": 30, "quarterly": 90, "yearly": 365}.get(period, 30)


class SubscriptionPlan(TimeStampedModel):
    name = models.CharField(_("nom"), max_length=80)
    slug = models.SlugField(max_length=90, unique=True, db_index=True)
    description = models.TextField(blank=True)

    price = models.PositiveIntegerField(
        _("prix (FCFA)"),
        help_text=_("Entier, en FCFA. Jamais un flottant."),
    )
    billing_period = models.CharField(
        max_length=12, choices=BillingPeriod.choices, default=BillingPeriod.MONTHLY
    )

    # Benefits are a flag set rather than free text so the ad selector can ask a
    # precise question ("does this subscriber get ad_free?") instead of parsing.
    ad_free = models.BooleanField(
        default=True,
        help_text=_("Les abonnes ne voient aucune publicite."),
    )
    benefits = models.JSONField(
        default=list, blank=True,
        help_text=_("Liste de libelles affiches sur la page d'abonnement."),
    )

    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("formule d'abonnement")
        verbose_name_plural = _("formules d'abonnement")
        ordering = ("display_order", "price")

    def __str__(self):
        return f"{self.name} ({self.price} FCFA/{self.get_billing_period_display()})"

    @property
    def period_days(self) -> int:
        return BillingPeriod.days(self.billing_period)


class SubscriptionStatus(models.TextChoices):
    PENDING = "pending", _("En attente de paiement")
    ACTIVE = "active", _("Actif")
    CANCELLED = "cancelled", _("Annule")
    EXPIRED = "expired", _("Expire")


class UserSubscriptionQuerySet(models.QuerySet):
    def active(self):
        """Active *and* not past its period end.

        Both conditions matter: the renewal task may not have run yet, and an
        expired-but-unswept row must never grant benefits.
        """
        return self.filter(
            status=SubscriptionStatus.ACTIVE, current_period_end__gt=timezone.now()
        )


class UserSubscription(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions"
    )

    status = models.CharField(
        max_length=12, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING, db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # False means "runs to the end of the paid period, then stops" — cancelling
    # must not confiscate time the user already paid for.
    auto_renew = models.BooleanField(default=True)
    renewal_failures = models.PositiveSmallIntegerField(default=0)

    objects = UserSubscriptionQuerySet.as_manager()

    class Meta:
        verbose_name = _("abonnement")
        verbose_name_plural = _("abonnements")
        ordering = ("-created_at",)
        constraints = [
            # One live subscription per user. Partial, so historical cancelled
            # and expired rows accumulate freely as a record.
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(status__in=["pending", "active"]),
                name="uniq_open_subscription_per_user",
            ),
        ]
        indexes = [models.Index(fields=["status", "current_period_end"])]

    def __str__(self):
        return f"{self.user_id} -> {self.plan.name} ({self.status})"

    @property
    def is_currently_active(self) -> bool:
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
        )

    @property
    def grants_ad_free(self) -> bool:
        return self.is_currently_active and self.plan.ad_free


# ==========================================================================
# Payments
# ==========================================================================
class PaymentProvider(models.TextChoices):
    ORANGE_MONEY = "orange_money", _("Orange Money")
    MOOV_MONEY = "moov_money", _("Moov Money")
    WAVE = "wave", _("Wave")
    CARD = "card", _("Carte bancaire")
    MOCK = "mock", _("Simulateur (developpement)")


class TransactionType(models.TextChoices):
    SUBSCRIPTION = "subscription", _("Souscription")
    RENEWAL = "renewal", _("Renouvellement")


class TransactionStatus(models.TextChoices):
    PENDING = "pending", _("En attente")
    COMPLETED = "completed", _("Complete")
    FAILED = "failed", _("Echoue")
    CANCELLED = "cancelled", _("Annule")


class Transaction(TimeStampedModel):
    """One payment attempt. Append-only in spirit: a failed attempt keeps its row.

    `idempotency_key` is unique at the database level, which is what makes a
    double-submitted checkout return the existing transaction instead of
    charging twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transactions"
    )
    subscription = models.ForeignKey(
        UserSubscription, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="transactions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan, null=True, blank=True,
        on_delete=models.PROTECT, related_name="transactions",
    )

    provider = models.CharField(max_length=20, choices=PaymentProvider.choices,
                                db_index=True)
    type = models.CharField(max_length=16, choices=TransactionType.choices,
                            default=TransactionType.SUBSCRIPTION)
    status = models.CharField(max_length=12, choices=TransactionStatus.choices,
                              default=TransactionStatus.PENDING, db_index=True)

    amount = models.PositiveIntegerField(
        _("montant (FCFA)"), validators=[MinValueValidator(1)],
        help_text=_("Entier, en FCFA."),
    )
    currency = models.CharField(max_length=3, default="XOF")

    idempotency_key = models.CharField(
        max_length=80, unique=True, db_index=True,
        help_text=_("Contrainte d'unicite en base: c'est elle qui empeche "
                    "un double paiement, pas une verification applicative."),
    )
    # What the provider calls this payment on their side.
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    payer_identifier = models.CharField(
        max_length=64, blank=True,
        help_text=_("Numero mobile money ou 4 derniers chiffres de la carte. "
                    "Jamais un PAN complet."),
    )

    failure_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Raw provider payloads, kept for reconciliation and dispute handling.
    provider_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("transaction")
        verbose_name_plural = _("transactions")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.amount} FCFA via {self.provider} ({self.status})"


class WebhookEvent(models.Model):
    """Every inbound provider callback, recorded before it is acted on.

    The unique constraint on (provider, event_id) is the replay guard: providers
    retry callbacks until they get a 2xx, so the same event *will* arrive more
    than once, and processing it twice would extend a subscription twice.
    """

    provider = models.CharField(max_length=20, choices=PaymentProvider.choices)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=60, blank=True)

    transaction = models.ForeignKey(
        Transaction, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="webhook_events",
    )
    payload = models.JSONField(default=dict)
    signature_valid = models.BooleanField(default=False)

    processed = models.BooleanField(default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("evenement webhook")
        verbose_name_plural = _("evenements webhook")
        ordering = ("-received_at",)
        constraints = [
            models.UniqueConstraint(fields=("provider", "event_id"),
                                    name="uniq_webhook_event_per_provider"),
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_id} ({'ok' if self.processed else 'pending'})"


# ==========================================================================
# Advertising
# ==========================================================================
def public_creative_storage():
    """Ad creatives go in the PUBLIC bucket.

    They are shown to every viewer, so the default (private) storage was wrong
    twice over: it signed each URL with a 6-hour expiry, and it built that URL
    against the internal `minio:9000` hostname, which no browser can resolve.
    Every ad rendered as a broken image.

    A callable rather than `storages["public"]` directly so the storage is
    resolved at runtime and the migration stays serialisable.
    """
    return storages["public"]



class AdPlacement(models.TextChoices):
    PRE_ROLL = "pre_roll", _("Avant la video")
    MID_ROLL = "mid_roll", _("Pendant la video")


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", _("Brouillon")
    ACTIVE = "active", _("Active")
    PAUSED = "paused", _("En pause")
    ENDED = "ended", _("Terminee")


class AdCampaignQuerySet(models.QuerySet):
    def eligible(self):
        """Campaigns that may be served right now.

        The impression cap is checked against the denormalised counter rather
        than a COUNT over AdImpression: ad selection runs on every playback and
        cannot afford an aggregate over the largest table in the schema.
        """
        now = timezone.now()
        return self.filter(
            status=CampaignStatus.ACTIVE,
            start_date__lte=now,
            end_date__gte=now,
        ).filter(
            models.Q(impression_cap=0)
            | models.Q(impression_count__lt=models.F("impression_cap"))
        )


class AdCampaign(TimeStampedModel):
    advertiser_name = models.CharField(_("annonceur"), max_length=120)
    title = models.CharField(_("titre"), max_length=200)

    # Creative: an image or a short video, stored in the public bucket since it
    # is served to every viewer anyway.
    creative = models.FileField(
        _("creative"), upload_to="ads/%Y/%m/",
        storage=public_creative_storage,
        help_text=_("Image (JPG/PNG/WebP) ou video courte (MP4). "
                    "Stockee dans le bucket public: une creative est vue par "
                    "tous les spectateurs."),
    )
    creative_is_video = models.BooleanField(default=False)
    click_url = models.URLField(_("lien de destination"), blank=True)

    placement = models.CharField(max_length=12, choices=AdPlacement.choices,
                                 default=AdPlacement.PRE_ROLL)
    duration_seconds = models.PositiveIntegerField(
        default=10,
        help_text=_("Duree d'affichage. Pour une image, duree imposee; pour une "
                    "video, duree maximale."),
    )
    skippable_after_seconds = models.PositiveIntegerField(
        default=5,
        help_text=_("0 = non ignorable."),
    )
    # Where in the video a mid-roll fires, as a fraction of its duration.
    mid_roll_position = models.FloatField(
        default=0.5,
        help_text=_("0.5 = a la moitie de la video. Ignore pour un pre-roll."),
    )

    start_date = models.DateTimeField(db_index=True)
    end_date = models.DateTimeField(db_index=True)
    impression_cap = models.PositiveIntegerField(
        default=0, help_text=_("0 = illimite."),
    )
    impression_count = models.PositiveIntegerField(default=0)
    completed_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)

    # Targeting is intentionally minimal — see the README scope note.
    categories = models.ManyToManyField(
        "catalog.Category", blank=True, related_name="ad_campaigns",
        help_text=_("Vide = toutes les categories."),
    )
    weight = models.PositiveSmallIntegerField(
        default=1,
        help_text=_("Poids relatif dans la rotation. Un poids 3 est servi trois "
                    "fois plus souvent qu'un poids 1."),
    )

    status = models.CharField(max_length=10, choices=CampaignStatus.choices,
                              default=CampaignStatus.DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ad_campaigns",
    )

    objects = AdCampaignQuerySet.as_manager()

    class Meta:
        verbose_name = _("campagne publicitaire")
        verbose_name_plural = _("campagnes publicitaires")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "start_date", "end_date"])]

    def __str__(self):
        return f"{self.advertiser_name} — {self.title}"

    @property
    def is_capped(self) -> bool:
        return self.impression_cap > 0 and self.impression_count >= self.impression_cap

    @property
    def completion_rate(self) -> float:
        return (self.completed_count / self.impression_count) if self.impression_count else 0.0


class AdImpression(models.Model):
    """One ad play. Written at selection time, updated when it finishes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE,
                                 related_name="impressions")
    video = models.ForeignKey(
        "videos.Video", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ad_impressions",
        help_text=_("Contenu contre lequel la publicite a ete diffusee."),
    )
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ad_impressions",
    )
    session_key = models.CharField(max_length=64, blank=True)

    placement = models.CharField(max_length=12, choices=AdPlacement.choices)
    played_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed = models.BooleanField(default=False, db_index=True)
    skipped = models.BooleanField(default=False)
    watched_seconds = models.PositiveIntegerField(default=0)
    clicked = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("impression publicitaire")
        verbose_name_plural = _("impressions publicitaires")
        ordering = ("-played_at",)
        indexes = [
            models.Index(fields=["campaign", "-played_at"]),
            models.Index(fields=["video", "-played_at"]),
        ]

    def __str__(self):
        return f"{self.campaign_id} on {self.video_id} ({'done' if self.completed else 'started'})"
