from django.urls import path

from apps.live.views import (
    LiveChannelDetailView,
    LiveChannelListView,
    LiveChatHistoryView,
    LiveNotReadyHookView,
    LiveReadyHookView,
    LivePlaylistAuthzView,
    MediaMTXAuthView,
    MyLiveChannelView,
    MyLiveSessionsView,
    RotateStreamKeyView,
)

app_name = "live"

urlpatterns = [
    # --- MediaMTX integration ------------------------------------------------
    # Internal only. nginx returns 404 for these paths at the edge; they are
    # reachable solely from inside the compose network.
    path("live/auth/", MediaMTXAuthView.as_view(), name="mediamtx-auth"),
    path("live/authz/", LivePlaylistAuthzView.as_view(), name="playlist-authz"),
    path("live/hooks/ready/", LiveReadyHookView.as_view(), name="hook-ready"),
    path("live/hooks/not-ready/", LiveNotReadyHookView.as_view(), name="hook-not-ready"),

    # --- Owner ---------------------------------------------------------------
    path("live/me/", MyLiveChannelView.as_view(), name="my-channel"),
    path("live/me/rotate-key/", RotateStreamKeyView.as_view(), name="rotate-key"),
    path("live/me/sessions/", MyLiveSessionsView.as_view(), name="my-sessions"),

    # --- Public --------------------------------------------------------------
    path("live/", LiveChannelListView.as_view(), name="live-list"),
    path("live/<slug:slug>/", LiveChannelDetailView.as_view(), name="live-detail"),
    path("live/<slug:slug>/chat/", LiveChatHistoryView.as_view(), name="live-chat"),
]
