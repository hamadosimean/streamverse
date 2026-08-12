"""Monetization serializers.

Money is exposed as an integer plus a preformatted string. The client never does
arithmetic on it, and never has to guess a locale's grouping rules.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.monetization.models import (
    AdCampaign,
    AdPlacement,
    CampaignStatus,
    PaymentProvider,
    SubscriptionPlan,
    Transaction,
    UserSubscription,
)


def format_fcfa(amount: int) -> str:
    """`12 000 FCFA` — narrow no-break space, the francophone convention."""
    return f"{amount:,}".replace(",", " ") + " FCFA"


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    price_display = serializers.SerializerMethodField()
    period_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = ("id", "slug", "name", "description", "price", "price_display",
                  "billing_period", "period_days", "ad_free", "benefits",
                  "display_order")
        read_only_fields = fields

    def get_price_display(self, obj) -> str:
        return format_fcfa(obj.price)


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    is_currently_active = serializers.BooleanField(read_only=True)
    grants_ad_free = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserSubscription
        fields = ("id", "plan", "status", "started_at", "current_period_end",
                  "cancelled_at", "auto_renew", "is_currently_active",
                  "grants_ad_free", "created_at")
        read_only_fields = fields


class TransactionSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    provider_label = serializers.CharField(source="get_provider_display",
                                           read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True, default=None)

    class Meta:
        model = Transaction
        fields = ("id", "provider", "provider_label", "type", "status", "amount",
                  "amount_display", "currency", "plan_name", "payer_identifier",
                  "failure_reason", "completed_at", "created_at")
        # Deliberately excludes idempotency_key, provider_reference and
        # provider_payload: internal reconciliation data, not user-facing.
        read_only_fields = fields

    def get_amount_display(self, obj) -> str:
        return format_fcfa(obj.amount)


class CheckoutSerializer(serializers.Serializer):
    """Start a subscription payment.

    Note what is *absent*: an amount. The price is read from the plan
    server-side, so a crafted request cannot choose what it pays.
    """

    plan_slug = serializers.SlugField()
    provider = serializers.ChoiceField(
        choices=[c for c, _ in PaymentProvider.choices if c != PaymentProvider.MOCK]
    )
    payer_identifier = serializers.CharField(
        max_length=64, required=False, allow_blank=True,
        help_text="Numero mobile money, ou 4 derniers chiffres de la carte.",
    )
    idempotency_key = serializers.CharField(
        max_length=80, required=False, allow_blank=True,
        help_text="Facultatif. Rejouer la meme cle renvoie la transaction "
                  "existante au lieu d'en creer une seconde.",
    )

    def validate(self, attrs):
        if attrs["provider"] != PaymentProvider.CARD and not attrs.get("payer_identifier"):
            raise serializers.ValidationError(
                {"payer_identifier": "Numero de telephone requis pour le mobile money."}
            )
        return attrs


class AdBreakSerializer(serializers.Serializer):
    """One ad slot in a playback plan (documentation shape)."""

    impression_id = serializers.UUIDField()
    campaign_id = serializers.IntegerField()
    placement = serializers.ChoiceField(choices=AdPlacement.choices)
    cue_seconds = serializers.IntegerField()
    advertiser_name = serializers.CharField()
    title = serializers.CharField()
    creative_url = serializers.URLField(allow_null=True)
    creative_is_video = serializers.BooleanField()
    click_url = serializers.CharField(allow_blank=True)
    duration_seconds = serializers.IntegerField()
    skippable_after_seconds = serializers.IntegerField()


class AdPlanSerializer(serializers.Serializer):
    ads_enabled = serializers.BooleanField()
    reason = serializers.CharField()
    breaks = AdBreakSerializer(many=True)
    delivery = serializers.CharField(required=False)


class AdImpressionEventSerializer(serializers.Serializer):
    watched_seconds = serializers.IntegerField(min_value=0, max_value=3600)
    completed = serializers.BooleanField(default=False)
    skipped = serializers.BooleanField(default=False)
    clicked = serializers.BooleanField(default=False)


class AdCampaignSerializer(serializers.ModelSerializer):
    """Admin-facing campaign representation."""

    creative_url = serializers.SerializerMethodField()
    completion_rate = serializers.FloatField(read_only=True)
    is_capped = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, default=None
    )
    category_slugs = serializers.SlugRelatedField(
        source="categories", slug_field="slug", many=True, required=False,
        queryset=AdCampaign.categories.field.related_model.objects.filter(is_active=True),
    )

    class Meta:
        model = AdCampaign
        fields = ("id", "advertiser_name", "title", "creative", "creative_url",
                  "creative_is_video", "click_url", "placement", "duration_seconds",
                  "skippable_after_seconds", "mid_roll_position", "start_date",
                  "end_date", "impression_cap", "impression_count",
                  "completed_count", "click_count", "completion_rate", "is_capped",
                  "category_slugs", "weight", "status", "created_by_username",
                  "created_at", "updated_at")
        read_only_fields = ("id", "creative_url", "impression_count",
                            "completed_count", "click_count", "completion_rate",
                            "is_capped", "created_by_username", "created_at",
                            "updated_at")
        extra_kwargs = {"creative": {"write_only": True, "required": False}}

    def get_creative_url(self, obj) -> str | None:
        return obj.creative.url if obj.creative else None

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_date": "La date de fin doit suivre la date de debut."}
            )

        position = attrs.get("mid_roll_position")
        if position is not None and not 0 < position < 1:
            raise serializers.ValidationError(
                {"mid_roll_position": "Valeur attendue entre 0 et 1 (exclus)."}
            )

        status_value = attrs.get("status", getattr(self.instance, "status", None))
        creative = attrs.get("creative", getattr(self.instance, "creative", None))
        if status_value == CampaignStatus.ACTIVE and not creative:
            raise serializers.ValidationError(
                {"creative": "Une campagne active doit avoir une creative."}
            )
        return attrs
