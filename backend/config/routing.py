"""WebSocket URL routing.

Two sockets, both under `/ws/`:

* transcoding progress — one per in-flight upload, owner-only;
* live chat + viewer count — one per live channel, open to anonymous viewers
  for reading, authenticated for posting.
"""
from django.urls import path

from apps.live.consumers import LiveChatConsumer
from apps.videos.consumers import UploadProgressConsumer

websocket_urlpatterns = [
    path("ws/uploads/<uuid:video_id>/", UploadProgressConsumer.as_asgi()),
    path("ws/live/<slug:slug>/", LiveChatConsumer.as_asgi()),
]
