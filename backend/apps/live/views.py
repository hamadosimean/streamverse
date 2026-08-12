"""Live API.

Two audiences:

* **MediaMTX hooks** (`/api/live/auth/`, `/api/live/hooks/*`) — machine-to-machine,
  reachable only from inside the compose network. nginx returns 404 for these
  paths at the edge, so they are not exposed publicly even though they sit under
  `/api/`.
* **Everything else** — the normal REST API for viewers and channel owners.
"""
from __future__ import annotations

import hmac
import logging
from urllib.parse import parse_qs

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.live import services
from apps.live.models import LiveChannel, LiveStatus
from apps.live.serializers import (
    LiveChatMessageSerializer,
    LiveRecordingSerializer,
    MediaMTXAuthSerializer,
    OwnerLiveChannelSerializer,
    PublicLiveChannelSerializer,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# MediaMTX integration
# --------------------------------------------------------------------------
@extend_schema(exclude=True)
class MediaMTXAuthView(APIView):
    """Publish/read authorisation for MediaMTX.

    MediaMTX cannot attach a shared-secret header to this call, so the endpoint
    is protected by network isolation: it is only routable inside the compose
    network, and nginx 404s the path at the edge. `200` allows, anything else
    denies.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = MediaMTXAuthSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("live auth: malformed payload %s", request.data)
            return Response(status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        action = data["action"]
        path = data["path"]

        # MediaMTX asks about its own API/metrics paths too; only publish and
        # read concern us.
        if action not in ("publish", "read"):
            return Response(status=status.HTTP_200_OK)
        if not path:
            return Response(status=status.HTTP_200_OK)

        try:
            if action == "publish":
                supplied = (parse_qs(data.get("query") or "").get("key") or [""])[0]
                channel = services.authorise_publish(path, supplied)
                logger.info("live auth: publish allowed for %s from %s",
                            channel.slug, data.get("ip"))
            else:
                channel = services.authorise_read(path)
        except services.LiveAuthDenied as exc:
            logger.warning("live auth: %s denied for path=%r (%s)",
                           action, path, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        return Response(status=status.HTTP_200_OK)


@extend_schema(exclude=True)
class LivePlaylistAuthzView(APIView):
    """Authorisation subrequest for nginx `auth_request`, called on every
    *playlist* fetch (never per segment).

    Kept deliberately tiny — one indexed lookup, cached — because it sits in
    front of a request that repeats every couple of seconds per viewer. Returns
    204 to allow and 403 to deny; nginx discards the body either way.

    This is what makes a takedown effective mid-broadcast: a player cannot keep
    playing without refreshing the playlist, so disabling a channel stops
    in-flight playback within one segment duration.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    CACHE_SECONDS = 5

    def get(self, request):
        from django.core.cache import cache

        path = (request.query_params.get("path") or "").rsplit("/", 1)[0]
        if not path:
            return Response(status=status.HTTP_403_FORBIDDEN)

        cache_key = f"live:authz:{path}"
        allowed = cache.get(cache_key)

        if allowed is None:
            try:
                services.authorise_read(path)
                allowed = True
            except services.LiveAuthDenied:
                allowed = False
            cache.set(cache_key, allowed, self.CACHE_SECONDS)

        return Response(status=status.HTTP_204_NO_CONTENT if allowed
                        else status.HTTP_403_FORBIDDEN)


class _HookView(APIView):
    """Base for the ready / notReady hooks.

    These *can* carry a shared secret (we control the command line MediaMTX
    runs), so they do — network isolation alone is one layer, not two.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def check_secret(self, request) -> None:
        expected = settings.LIVE_HOOK_SECRET
        supplied = request.headers.get("X-Live-Hook-Secret", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            raise PermissionDenied("Signature de hook invalide.")

    def get_channel(self, request) -> LiveChannel:
        path = request.data.get("path") or ""
        try:
            return services.resolve_channel(path)
        except services.LiveAuthDenied as exc:
            raise ValidationError({"path": str(exc)}) from exc


@extend_schema(exclude=True)
class LiveReadyHookView(_HookView):
    """MediaMTX `runOnReady`: the publisher connected and media is flowing."""

    def post(self, request):
        self.check_secret(request)
        channel = self.get_channel(request)
        session = services.start_session(channel)
        return Response({"status": "live", "session_id": session.pk})


@extend_schema(exclude=True)
class LiveNotReadyHookView(_HookView):
    """MediaMTX `runOnNotReady`: the publisher disconnected."""

    def post(self, request):
        self.check_secret(request)
        channel = self.get_channel(request)
        session = services.end_session(channel)
        return Response({"status": "ended",
                         "session_id": session.pk if session else None})


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------
@extend_schema(tags=["live"])
class LiveChannelListView(ListAPIView):
    """Channels currently broadcasting, most-watched first."""

    permission_classes = [AllowAny]
    serializer_class = PublicLiveChannelSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            LiveChannel.objects.filter(
                status=LiveStatus.LIVE, is_enabled=True, user__is_suspended=False
            )
            .select_related("user", "category")
            .order_by("-current_viewer_count", "-started_at")
        )


@extend_schema(tags=["live"])
class LiveChannelDetailView(APIView):
    """One channel by slug. Never exposes the stream key."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: PublicLiveChannelSerializer})
    def get(self, request, slug):
        channel = get_object_or_404(
            LiveChannel.objects.select_related("user", "category"),
            slug=slug, is_enabled=True, user__is_suspended=False,
        )
        data = PublicLiveChannelSerializer(channel, context={"request": request}).data
        # Read through Redis: the DB column is only refreshed on join/leave.
        data["current_viewer_count"] = services.current_viewers(slug)
        return Response(data)


@extend_schema(tags=["live"])
class LiveChatHistoryView(ListAPIView):
    """Chat backlog for the current session — the REST fallback for a client
    whose WebSocket could not connect."""

    permission_classes = [AllowAny]
    serializer_class = LiveChatMessageSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from apps.live.models import LiveChatMessage

            return LiveChatMessage.objects.none()
        channel = get_object_or_404(LiveChannel, slug=self.kwargs["slug"])
        return services.recent_chat(channel, limit=100)


# --------------------------------------------------------------------------
# Owner
# --------------------------------------------------------------------------
@extend_schema(tags=["live"])
class MyLiveChannelView(APIView):
    """The caller's own channel: read, update, and create-on-first-access.

    Created lazily rather than on signup — most accounts never stream, and a
    dormant row per user is a row that can leak a credential for no reason.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = OwnerLiveChannelSerializer

    def get_or_create_channel(self, request) -> LiveChannel:
        channel = LiveChannel.objects.filter(user=request.user).first()
        if channel is not None:
            return channel

        # Slug defaults to the username; disambiguated if that is somehow taken.
        base = slugify(request.user.username)[:36] or "chaine"
        slug = base
        suffix = 1
        while LiveChannel.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"{base}-{suffix}"[:40]

        return LiveChannel.objects.create(
            user=request.user,
            slug=slug,
            title=f"Direct de {request.user.display_name or request.user.username}",
        )

    @extend_schema(responses={200: OwnerLiveChannelSerializer})
    def get(self, request):
        channel = self.get_or_create_channel(request)
        return Response(
            OwnerLiveChannelSerializer(channel, context={"request": request}).data
        )

    @extend_schema(request=OwnerLiveChannelSerializer,
                   responses={200: OwnerLiveChannelSerializer})
    def patch(self, request):
        channel = self.get_or_create_channel(request)
        serializer = OwnerLiveChannelSerializer(
            channel, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(tags=["live"])
class RotateStreamKeyView(APIView):
    """Issue a new stream key, invalidating the old one immediately."""

    permission_classes = [IsAuthenticated]
    serializer_class = OwnerLiveChannelSerializer
    throttle_scope = "live_start"

    @extend_schema(request=None, responses={200: OwnerLiveChannelSerializer})
    def post(self, request):
        channel = LiveChannel.objects.filter(user=request.user).first()
        if channel is None:
            raise ValidationError({"detail": "Aucune chaine en direct configuree."})

        if channel.is_live:
            # Rotating mid-broadcast would not kill the current RTMP session
            # (MediaMTX authorised it at connect time), so the user would think
            # they had revoked access when they had not.
            raise ValidationError(
                {"detail": "Arretez le direct avant de regenerer la cle de flux."}
            )

        channel.rotate_stream_key()
        audit.record(AuditAction.LIVE_KEY_ROTATED, actor=request.user,
                     target=channel, request=request)

        return Response(
            OwnerLiveChannelSerializer(channel, context={"request": request}).data
        )


@extend_schema(tags=["live"])
class MyLiveSessionsView(ListAPIView):
    """Past broadcasts and what became of their recordings."""

    permission_classes = [IsAuthenticated]
    serializer_class = LiveRecordingSerializer

    def get_queryset(self):
        from apps.live.models import LiveRecording

        if getattr(self, "swagger_fake_view", False):
            return LiveRecording.objects.none()

        # Scoped by ownership at the database level, and an empty queryset (not
        # an empty list) when the user has never opened a channel.
        return (
            LiveRecording.objects.filter(live_channel__user=self.request.user)
            .select_related("converted_video")
            .order_by("-started_at")
        )
