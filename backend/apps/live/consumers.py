"""Live chat + viewer-count WebSocket.

One socket per viewer carries both concerns: the chat stream and the viewer
count are the same audience, and opening two connections per viewer to a
channel layer would double the connection count for no benefit.

Anonymous viewers may connect (they are part of the audience and should see the
count and the chat) but may not post — enforced here, not in the UI.
"""
from __future__ import annotations

import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from apps.live import services
from apps.live.models import LiveChannel

logger = logging.getLogger(__name__)


class LiveChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group = services.chat_group(self.slug)
        self.user = self.scope.get("user")
        self._last_message_at = 0.0
        self._joined = False

        channel = await self._load_channel(self.slug)
        if channel is None:
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        self._joined = True

        count = await database_sync_to_async(services.viewer_joined)(self.slug)

        # Prime the newcomer: current state plus the recent backlog, so joining
        # mid-stream is not an empty box.
        await self.send_json(
            {
                "type": "live.hello",
                "slug": self.slug,
                "status": channel["status"],
                "chat_enabled": channel["chat_enabled"],
                "can_chat": bool(self.user and self.user.is_authenticated),
                "viewer_count": count,
                "messages": await self._backlog(self.slug),
            }
        )
        await self._broadcast_viewers(count)

    async def disconnect(self, code):
        if not getattr(self, "_joined", False):
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)
        count = await database_sync_to_async(services.viewer_left)(self.slug)
        await self._broadcast_viewers(count)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")

        if kind == "ping":
            await self.send_json({"type": "pong"})
            return

        if kind != "chat.send":
            return

        if not self.user or not self.user.is_authenticated:
            await self.send_json({"type": "live.error", "code": "unauthenticated",
                                  "detail": "Connectez-vous pour participer au chat."})
            return

        # Per-connection flood guard. The DRF throttles never see a WebSocket
        # frame, so without this one client could fill the channel layer.
        now = time.monotonic()
        if now - self._last_message_at < settings.LIVE_CHAT_MIN_INTERVAL_SECONDS:
            await self.send_json({"type": "live.error", "code": "rate_limited",
                                  "detail": "Vous envoyez des messages trop vite."})
            return

        text = (content.get("content") or "").strip()
        if not text:
            return
        if len(text) > 500:
            text = text[:500]

        try:
            message = await self._store(self.slug, self.user, text)
        except ValueError as exc:
            await self.send_json({"type": "live.error", "code": "rejected",
                                  "detail": str(exc)})
            return

        self._last_message_at = now
        await self.channel_layer.group_send(
            self.group, {"type": "chat.message", **message}
        )

    # -- group handlers ---------------------------------------------------
    async def chat_message(self, event):
        await self.send_json({k: v for k, v in event.items() if k != "type"}
                             | {"type": "chat.message"})

    async def live_viewers(self, event):
        await self.send_json({"type": "live.viewers", "count": event["count"]})

    async def live_status(self, event):
        await self.send_json({"type": "live.status", "status": event["status"],
                              "session_id": event.get("session_id")})

    # -- helpers ----------------------------------------------------------
    async def _broadcast_viewers(self, count):
        await self.channel_layer.group_send(
            self.group, {"type": "live.viewers", "count": count}
        )

    @database_sync_to_async
    def _load_channel(self, slug):
        channel = LiveChannel.objects.select_related("user").filter(slug=slug).first()
        if channel is None or not channel.is_enabled or channel.user.is_suspended:
            return None
        return {"status": channel.status, "chat_enabled": channel.chat_enabled}

    @database_sync_to_async
    def _backlog(self, slug):
        channel = LiveChannel.objects.filter(slug=slug).first()
        if channel is None:
            return []
        return [
            {
                "id": m.id,
                "user": m.user.display_name or m.user.username,
                "username": m.user.username,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in services.recent_chat(channel)
        ]

    @database_sync_to_async
    def _store(self, slug, user, text):
        channel = LiveChannel.objects.get(slug=slug)
        message = services.post_chat_message(channel, user, text)
        return {
            "id": message.id,
            "user": user.display_name or user.username,
            "username": user.username,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
