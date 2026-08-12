"""Monetization API: plans, checkout, webhooks, ads, campaign admin."""
from __future__ import annotations

import logging

from django.db import IntegrityError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.core.permissions import IsAdmin
from apps.core.sorting import SortableMixin, SortOption
from apps.monetization.models import (
    AdCampaign,
    SubscriptionPlan,
    Transaction,
    TransactionStatus,
    UserSubscription,
    WebhookEvent,
)
from apps.monetization.providers.base import SignatureError
from apps.monetization.providers.registry import available_providers, get_provider
from apps.monetization.serializers import (
    AdCampaignSerializer,
    AdImpressionEventSerializer,
    AdPlanSerializer,
    CheckoutSerializer,
    SubscriptionPlanSerializer,
    TransactionSerializer,
    UserSubscriptionSerializer,
)
from apps.monetization.services import ads as ad_service
from apps.monetization.services import payments as payment_service
from apps.videos.models import Video

logger = logging.getLogger(__name__)


# ==========================================================================
# Plans & checkout
# ==========================================================================
@extend_schema(tags=["monetization"])
class SubscriptionPlanListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = SubscriptionPlanSerializer
    pagination_class = None

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True).order_by(
            "display_order", "price"
        )


@extend_schema(tags=["monetization"])
class PaymentProviderListView(APIView):
    """Checkout options.

    Served by the API rather than hardcoded in the client, so swapping the mock
    for real providers changes what the UI offers without a frontend release.
    """

    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from django.conf import settings

        return Response({
            "providers": available_providers(),
            # The UI shows a banner because of this flag. A payment simulator
            # that looks identical to a real one is how demo money becomes a
            # support ticket.
            "sandbox": settings.PAYMENTS_USE_MOCK,
        })


@extend_schema(tags=["monetization"])
class CheckoutView(APIView):
    """Start a subscription payment. Returns a **pending** transaction.

    Activation happens when the provider's webhook arrives — a provider that has
    not confirmed has not paid.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CheckoutSerializer
    throttle_scope = "checkout"

    @extend_schema(request=CheckoutSerializer, responses={201: TransactionSerializer})
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = get_object_or_404(SubscriptionPlan, slug=data["plan_slug"],
                                 is_active=True)

        try:
            payment = payment_service.start_subscription_checkout(
                user=request.user,
                plan=plan,
                provider_code=data["provider"],
                payer_identifier=data.get("payer_identifier", ""),
                idempotency_key=data.get("idempotency_key") or None,
                request=request,
            )
        except payment_service.CheckoutError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return Response(
            TransactionSerializer(payment).data, status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["monetization"])
class TransactionStatusView(APIView):
    """Poll one transaction.

    Polling, not a WebSocket: a payment confirmation is a single state change a
    user waits seconds for, and a socket per checkout would be more machinery
    than the problem needs.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    @extend_schema(responses={200: TransactionSerializer})
    def get(self, request, transaction_id):
        payment = get_object_or_404(
            Transaction.objects.select_related("plan"),
            pk=transaction_id, user=request.user,
        )
        return Response(TransactionSerializer(payment).data)


@extend_schema(tags=["monetization"])
class MySubscriptionView(APIView):
    """The caller's current subscription, plus payment history."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSubscriptionSerializer

    @extend_schema(responses={200: dict})
    def get(self, request):
        subscription = (
            UserSubscription.objects.filter(user=request.user)
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )
        history = (
            Transaction.objects.filter(user=request.user)
            .select_related("plan")
            .order_by("-created_at")[:20]
        )
        return Response({
            "subscription": (UserSubscriptionSerializer(subscription).data
                             if subscription else None),
            "is_ad_free": ad_service.viewer_is_ad_free(request.user),
            "transactions": TransactionSerializer(history, many=True).data,
        })

    @extend_schema(request=None, responses={200: UserSubscriptionSerializer})
    def delete(self, request):
        """Cancel auto-renewal, keeping access to the end of the paid period."""
        subscription = UserSubscription.objects.filter(
            user=request.user, status__in=["pending", "active"]
        ).select_related("plan").first()
        if subscription is None:
            raise ValidationError({"detail": "Aucun abonnement actif."})

        payment_service.cancel_subscription(subscription, request=request)
        return Response(UserSubscriptionSerializer(subscription).data)


# ==========================================================================
# Webhooks
# ==========================================================================
@extend_schema(exclude=True)
class PaymentWebhookView(APIView):
    """Inbound provider callback.

    Order matters and is deliberate:

    1. **Verify the signature before looking at the payload.** An unauthenticated
       body is attacker-controlled data.
    2. **Record the event, keyed uniquely per (provider, event_id).** Providers
       retry until they get a 2xx, so duplicates are normal, not exceptional.
    3. **Return 200 on a duplicate.** Answering with an error would make the
       provider retry forever.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    # The raw body is what the signature covers; a parsed dict is not.
    parser_classes = []

    def post(self, request, provider_code):
        try:
            provider = get_provider(provider_code)
        except KeyError:
            return Response({"detail": "Fournisseur inconnu."},
                            status=status.HTTP_404_NOT_FOUND)

        body = request.body
        headers = {k: v for k, v in request.headers.items()}

        try:
            result = provider.verify_webhook(headers=headers, body=body)
        except SignatureError as exc:
            logger.warning("webhook %s rejected: %s", provider_code, exc)
            # 400, not 401: the provider should not retry a payload that will
            # never authenticate.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payment = Transaction.objects.filter(
            provider_reference=result.provider_reference
        ).first()

        try:
            event = WebhookEvent.objects.create(
                provider=provider_code,
                event_id=result.event_id,
                event_type=result.event_type,
                transaction=payment,
                payload=result.raw,
                signature_valid=True,
            )
        except IntegrityError:
            # Already seen. Acknowledge so the provider stops retrying.
            logger.info("webhook %s replay ignored: %s", provider_code, result.event_id)
            return Response({"detail": "Evenement deja traite.", "duplicate": True},
                            status=status.HTTP_200_OK)

        try:
            outcome = payment_service.apply_webhook_outcome(event)
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
        except Exception as exc:
            event.processing_error = str(exc)[:2000]
            event.save(update_fields=["processing_error"])
            logger.exception("webhook processing failed for %s", result.event_id)
            # 500 so the provider retries; the replay guard makes that safe.
            return Response({"detail": "Erreur de traitement."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"detail": "ok", "outcome": outcome},
                        status=status.HTTP_200_OK)


# ==========================================================================
# Ads
# ==========================================================================
@extend_schema(tags=["ads"])
class AdPlanView(APIView):
    """What plays around this video, decided server-side.

    The subscriber ad-free check happens here, not in the player: a client-side
    check is a suggestion.
    """

    permission_classes = [AllowAny]
    serializer_class = AdPlanSerializer

    @extend_schema(request=None, responses={200: AdPlanSerializer})
    def post(self, request, video_id):
        user = request.user if request.user.is_authenticated else None
        video = get_object_or_404(Video.objects.visible_to(user), pk=video_id)

        if not request.session.session_key:
            request.session.save()

        plan = ad_service.select_ads_for_playback(
            video=video, user=user, session_key=request.session.session_key or "",
        )
        return Response(plan)


@extend_schema(tags=["ads"])
class AdImpressionEventView(APIView):
    """Report how an ad played out (progress, completion, skip, click)."""

    permission_classes = [AllowAny]
    serializer_class = AdImpressionEventSerializer

    @extend_schema(request=AdImpressionEventSerializer, responses={200: dict})
    def post(self, request, impression_id):
        serializer = AdImpressionEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        impression = ad_service.record_impression_progress(
            impression_id=impression_id, **serializer.validated_data
        )
        if impression is None:
            return Response({"detail": "Impression inconnue."},
                            status=status.HTTP_404_NOT_FOUND)

        return Response({
            "impression_id": str(impression.pk),
            "completed": impression.completed,
            "skipped": impression.skipped,
            "clicked": impression.clicked,
        })


# ==========================================================================
# Admin: ad campaigns (a decision workflow, hence a React view not admin CRUD)
# ==========================================================================
@extend_schema(tags=["ads-admin"])
class AdCampaignViewSet(SortableMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdCampaignSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    sort_options = {
        "recent": SortOption("recent", ("-created_at", "-id")),
        "oldest": SortOption("oldest", ("created_at", "id")),
        "impressions": SortOption("impressions", ("-impression_count", "-id")),
        "clicks": SortOption("clicks", ("-click_count", "-id")),
        # The two an ad operator actually scans for: what stops soon, and what
        # is about to burn through its inventory.
        "ending": SortOption("ending", ("end_date", "id")),
        "advertiser": SortOption("advertiser", ("advertiser_name", "title")),
    }
    default_sort = "recent"

    def get_queryset(self):
        queryset = AdCampaign.objects.select_related("created_by").prefetch_related(
            "categories"
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return self.apply_sort(queryset)

    def perform_create(self, serializer):
        campaign = serializer.save(created_by=self.request.user)
        audit.record(AuditAction.CAMPAIGN_CHANGED, actor=self.request.user,
                     target=campaign, metadata={"event": "created"},
                     request=self.request)

    def perform_update(self, serializer):
        previous_status = serializer.instance.status
        campaign = serializer.save()
        audit.record(
            AuditAction.CAMPAIGN_CHANGED, actor=self.request.user, target=campaign,
            metadata={"event": "updated", "from_status": previous_status,
                      "to_status": campaign.status,
                      "fields": list(serializer.validated_data.keys())},
            request=self.request,
        )

    def perform_destroy(self, instance):
        audit.record(AuditAction.CAMPAIGN_CHANGED, actor=self.request.user,
                     target=instance, metadata={"event": "deleted"},
                     request=self.request)
        instance.delete()

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Headline numbers for the admin dashboard."""
        campaigns = AdCampaign.objects.aggregate(
            total=Count("id"),
            impressions=Sum("impression_count"),
            completed=Sum("completed_count"),
            clicks=Sum("click_count"),
        )
        revenue = Transaction.objects.filter(
            status=TransactionStatus.COMPLETED
        ).aggregate(total=Sum("amount"), count=Count("id"))

        impressions = campaigns["impressions"] or 0
        return Response({
            "campaigns": campaigns["total"] or 0,
            "active_campaigns": AdCampaign.objects.eligible().count(),
            "impressions": impressions,
            "completed": campaigns["completed"] or 0,
            "clicks": campaigns["clicks"] or 0,
            "completion_rate": round((campaigns["completed"] or 0) / impressions, 4)
            if impressions else 0,
            "revenue_fcfa": revenue["total"] or 0,
            "paid_transactions": revenue["count"] or 0,
            "active_subscriptions": UserSubscription.objects.active().count(),
        })
