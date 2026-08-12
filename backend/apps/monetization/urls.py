from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.monetization.views import (
    AdCampaignViewSet,
    AdImpressionEventView,
    AdPlanView,
    CheckoutView,
    MySubscriptionView,
    PaymentProviderListView,
    PaymentWebhookView,
    SubscriptionPlanListView,
    TransactionStatusView,
)

app_name = "monetization"

router = DefaultRouter()
router.register("admin/ad-campaigns", AdCampaignViewSet, basename="ad-campaign")

urlpatterns = [
    # Subscriptions
    path("monetization/plans/", SubscriptionPlanListView.as_view(), name="plan-list"),
    path("monetization/providers/", PaymentProviderListView.as_view(),
         name="provider-list"),
    path("monetization/checkout/", CheckoutView.as_view(), name="checkout"),
    path("monetization/transactions/<uuid:transaction_id>/",
         TransactionStatusView.as_view(), name="transaction-status"),
    path("monetization/subscription/", MySubscriptionView.as_view(),
         name="my-subscription"),

    # Provider callbacks. Public by necessity — the provider calls them from its
    # own infrastructure — and authenticated by HMAC signature, not by session.
    path("monetization/webhooks/<str:provider_code>/", PaymentWebhookView.as_view(),
         name="payment-webhook"),

    # Ads
    path("videos/<uuid:video_id>/ads/", AdPlanView.as_view(), name="ad-plan"),
    path("ads/impressions/<uuid:impression_id>/", AdImpressionEventView.as_view(),
         name="ad-impression-event"),
]

urlpatterns += router.urls
