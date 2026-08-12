from django.urls import path

from apps.accounts.views import (
    ChangePasswordView,
    ChannelVideosView,
    MeView,
    PublicChannelView,
)

app_name = "accounts"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/password/", ChangePasswordView.as_view(), name="change-password"),
    path("channels/<str:username>/", PublicChannelView.as_view(), name="public-channel"),
    path("channels/<str:username>/videos/", ChannelVideosView.as_view(),
         name="channel-videos"),
]
