"""WebSocket consumer for transcoding progress.

Authentication comes from the JWT in the handshake query string
(`apps.core.ws_auth`), but that only establishes *who* is connecting. Ownership
of the specific video is re-checked here before the socket is allowed to join the
group — a valid token for user A must not be able to watch user B's upload
progress.
"""
from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.videos.models import Video
from apps.videos.services.progress import group_name

logger = logging.getLogger(__name__)


class UploadProgressConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.video_id = self.scope["url_route"]["kwargs"]["video_id"]
        user = self.scope.get("user")

        if user is None or not user.is_authenticated:
            await self.close(code=4401)  # unauthenticated
            return

        snapshot = await self._authorised_snapshot(self.video_id, user)
        if snapshot is None:
            await self.close(code=4403)  # not yours
            return

        self.group = group_name(self.video_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

        # Send current state immediately: a client that connects late (or
        # reconnects after a refresh) must not stare at 0% until the next frame.
        await self.send_json({"type": "progress.update", **snapshot})

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Read-only channel. Answer pings so intermediaries keep it open.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def progress_update(self, event):
        """Handler for `group_send(type="progress.update")`."""
        payload = {k: v for k, v in event.items() if k != "type"}
        await self.send_json({"type": "progress.update", **payload})

    @database_sync_to_async
    def _authorised_snapshot(self, video_id, user) -> dict | None:
        try:
            video = Video.objects.get(pk=video_id)
        except (Video.DoesNotExist, ValueError):
            return None
        if video.uploader_id != user.pk and not user.is_staff_member:
            return None
        return {
            "video_id": str(video.pk),
            "status": video.status,
            "stage": video.processing_stage,
            "percent": video.processing_progress,
            "detail": video.failure_reason or video.get_processing_stage_display(),
            "terminal": video.status in ("ready", "failed"),
        }
