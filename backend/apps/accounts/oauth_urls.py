"""Sign-in-provider endpoints, mounted under /api/auth/ next to Djoser's."""
from django.urls import path

from apps.accounts.views import (
    AuthProvidersView,
    GoogleAuthorizeView,
    GoogleCallbackView,
)

app_name = "oauth"

urlpatterns = [
    path("providers/", AuthProvidersView.as_view(), name="providers"),
    path("google/authorize/", GoogleAuthorizeView.as_view(), name="google-authorize"),
    path("google/callback/", GoogleCallbackView.as_view(), name="google-callback"),
]
