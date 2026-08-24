"""Live session lifecycle, stream-key auth and viewer counting."""
from __future__ import annotations

import hmac
import logging
import secrets

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.live.models import LiveChannel, LiveChatMessage, LiveRecording, LiveStatus

logger = logging.getLogger(__name__)


def chat_group(slug: str) -> str:
    return f"live_chat_{slug}"


def viewers_key(slug: str) -> str:
    return f"live:viewers:{slug}"


# --------------------------------------------------------------------------
# Stream-key authentication (called by the MediaMTX auth hook)
# --------------------------------------------------------------------------
class LiveAuthDenied(Exception):
    pass


def resolve_channel(path: str) -> LiveChannel:
    """Map a MediaMTX path back to its channel.

    Two prefixes resolve to the same channel: `live/<slug>` (RTMP, and the
    bridged output of a browser broadcast) and `webrtc/<slug>` (a browser
    publishing over WHIP, before the bridge).
    """
    for prefix in (f"{settings.LIVE_RTMP_APP}/", f"{settings.LIVE_WEBRTC_APP}/"):
        if path.startswith(prefix):
            slug = path[len(prefix):].strip("/")
            break
    else:
        raise LiveAuthDenied(f"Chemin non gere: {path}")

    try:
        return LiveChannel.objects.select_related("user").get(slug=slug)
    except LiveChannel.DoesNotExist as exc:
        raise LiveAuthDenied(f"Chaine inconnue: {slug}") from exc


# --------------------------------------------------------------------------
# Browser publish tickets
#
# A ticket is what a phone or a laptop publishes with instead of the channel's
# permanent stream key. It is minted for the authenticated owner, lives in the
# cache with a TTL of a few minutes, and is bound to one channel.
#
# Not single-use: WHIP re-authorises on an ICE restart, and a broadcast that
# died because the user walked between two wifi access points would be a worse
# bug than the few minutes of replay window a TTL leaves open.
# --------------------------------------------------------------------------
def ticket_key(token: str) -> str:
    return f"live:whip-ticket:{token}"


def issue_publish_ticket(channel: LiveChannel) -> tuple[str, int]:
    """Mint a short-lived publish credential. Returns (token, ttl_seconds)."""
    token = secrets.token_urlsafe(32)
    ttl = settings.LIVE_WHIP_TICKET_TTL_SECONDS
    cache.set(ticket_key(token), channel.slug, timeout=ttl)
    logger.info("live: issued publish ticket for %s (ttl %ss)", channel.slug, ttl)
    return token, ttl


def whip_url(channel: LiveChannel, ticket: str) -> str:
    """Same-origin WHIP endpoint, with the ticket as its credential.

    Note the path: `webrtc/<slug>`, not `live/<slug>`. The browser publishes to
    the staging path that the bridge reads from.
    """
    return (f"{settings.LIVE_WEBRTC_PUBLIC_PATH}/{settings.LIVE_WEBRTC_APP}/"
            f"{channel.slug}/whip?key={ticket}")


def _ticket_matches(token: str, channel: LiveChannel) -> bool:
    if not token:
        return False
    slug = cache.get(ticket_key(token))
    return bool(slug) and hmac.compare_digest(str(slug), channel.slug)


def _is_bridge(supplied_key: str, ip: str) -> bool:
    """Is this the in-container ffmpeg bridge republishing a browser stream?

    Two conditions, both required: the hook secret, and a source address inside
    MediaMTX itself. The bridge publishes to 127.0.0.1, so a request carrying
    the secret from anywhere else is not the bridge — it is someone who read the
    secret out of a config file and is trying to publish as any channel at all.
    """
    expected = settings.LIVE_HOOK_SECRET
    if not expected or not hmac.compare_digest(supplied_key, expected):
        return False
    return ip in ("127.0.0.1", "::1", "")


def authorise_publish(path: str, supplied_key: str, *, is_bridge: bool = False,
                      ip: str = "") -> LiveChannel:
    """Validate a publisher.

    Three credentials are accepted, in order of how much they can do:

    * the channel's **stream key** — OBS, ffmpeg, anything RTMP;
    * a **publish ticket** — a browser going live, valid for minutes;
    * the **hook secret from inside MediaMTX** — the ffmpeg bridge, and only
      when the request also declares itself the bridge and comes from loopback.

    Every comparison is constant-time: a plain `==` on a secret leaks its prefix
    through timing to anyone who can measure the auth endpoint.
    """
    channel = resolve_channel(path)

    if not channel.is_enabled:
        raise LiveAuthDenied("Diffusion desactivee pour cette chaine.")
    if channel.user.is_suspended or not channel.user.is_active:
        raise LiveAuthDenied("Compte non autorise a diffuser.")

    if not supplied_key:
        raise LiveAuthDenied("Cle de flux manquante.")

    if is_bridge:
        if not _is_bridge(supplied_key, ip):
            raise LiveAuthDenied("Relais non authentifie.")
        return channel

    if hmac.compare_digest(supplied_key, channel.stream_key):
        return channel
    if _ticket_matches(supplied_key, channel):
        return channel

    raise LiveAuthDenied("Cle de flux invalide.")


def authorise_read(path: str) -> LiveChannel:
    """Validate a viewer.

    Deliberately permissive — a public live stream is public. It still refuses
    to serve a channel that is disabled or whose owner is suspended, so a
    takedown takes effect on the media path and not only in the UI.
    """
    channel = resolve_channel(path)
    if not channel.is_enabled or channel.user.is_suspended:
        raise LiveAuthDenied("Ce direct n'est pas disponible.")
    return channel


# --------------------------------------------------------------------------
# Session lifecycle (called by the MediaMTX ready / notReady hooks)
# --------------------------------------------------------------------------
def start_session(channel: LiveChannel) -> LiveRecording:
    """The stream became ready: flip to live and open a session.

    Idempotent — MediaMTX can fire `runOnReady` again after a brief publisher
    reconnect, and that must not create a second session or reset the viewer
    count of an ongoing broadcast.
    """
    with transaction.atomic():
        locked = LiveChannel.objects.select_for_update().get(pk=channel.pk)

        active = locked.recordings.filter(ended_at__isnull=True).first()
        if locked.status == LiveStatus.LIVE and active is not None:
            logger.info("live: %s already live, reusing session %s",
                        locked.slug, active.pk)
            return active

        session = LiveRecording.objects.create(
            live_channel=locked, started_at=timezone.now()
        )
        locked.status = LiveStatus.LIVE
        locked.started_at = session.started_at
        locked.ended_at = None
        locked.peak_viewer_count = 0
        locked.current_viewer_count = 0
        locked.total_sessions = F("total_sessions") + 1
        locked.save(update_fields=["status", "started_at", "ended_at",
                                   "peak_viewer_count", "current_viewer_count",
                                   "total_sessions", "updated_at"])

    cache.set(viewers_key(channel.slug), 0, timeout=None)
    broadcast(channel.slug, {"type": "live.status", "status": LiveStatus.LIVE,
                             "session_id": session.pk})
    logger.info("live: %s went live (session %s)", channel.slug, session.pk)
    return session


def end_session(channel: LiveChannel) -> LiveRecording | None:
    """The stream stopped: close the session and queue the recording."""
    from apps.live.tasks import convert_recording_to_vod

    with transaction.atomic():
        locked = LiveChannel.objects.select_for_update().get(pk=channel.pk)
        session = locked.recordings.filter(ended_at__isnull=True).order_by(
            "-started_at"
        ).first()

        now = timezone.now()
        if session is not None:
            session.ended_at = now
            session.peak_viewer_count = locked.peak_viewer_count
            session.chat_message_count = session.chat_messages.count()
            session.save(update_fields=["ended_at", "peak_viewer_count",
                                        "chat_message_count", "updated_at"])

        locked.status = LiveStatus.ENDED
        locked.ended_at = now
        locked.current_viewer_count = 0
        locked.save(update_fields=["status", "ended_at", "current_viewer_count",
                                   "updated_at"])

    cache.delete(viewers_key(channel.slug))
    broadcast(channel.slug, {"type": "live.status", "status": LiveStatus.ENDED,
                             "session_id": session.pk if session else None})
    logger.info("live: %s ended (session %s)", channel.slug,
                session.pk if session else None)

    if session is not None and channel.record_sessions:
        # The recording files are still being flushed by MediaMTX; the task
        # waits for the path to settle before touching it.
        transaction.on_commit(
            lambda: convert_recording_to_vod.apply_async(
                args=[session.pk], countdown=settings.LIVE_RECORDING_SETTLE_SECONDS
            )
        )

    return session


# --------------------------------------------------------------------------
# Viewer counting
#
# Counted from our own WebSocket connections rather than from MediaMTX's reader
# count: that measures people watching *on this site*, which is what a viewer
# badge means, and it needs no polling.
# --------------------------------------------------------------------------
def _set_viewers(channel_slug: str, count: int) -> int:
    count = max(0, count)
    cache.set(viewers_key(channel_slug), count, timeout=None)

    updates = {"current_viewer_count": count}
    channel = LiveChannel.objects.filter(slug=channel_slug).only(
        "pk", "peak_viewer_count", "all_time_peak_viewers"
    ).first()
    if channel:
        if count > channel.peak_viewer_count:
            updates["peak_viewer_count"] = count
        if count > channel.all_time_peak_viewers:
            updates["all_time_peak_viewers"] = count
        LiveChannel.objects.filter(pk=channel.pk).update(**updates)

    return count


def viewer_joined(channel_slug: str) -> int:
    try:
        count = cache.incr(viewers_key(channel_slug))
    except ValueError:
        # Key absent (first viewer, or Redis restarted mid-stream).
        count = 1
    return _set_viewers(channel_slug, count)


def viewer_left(channel_slug: str) -> int:
    try:
        count = cache.decr(viewers_key(channel_slug))
    except ValueError:
        count = 0
    return _set_viewers(channel_slug, count)


def current_viewers(channel_slug: str) -> int:
    return int(cache.get(viewers_key(channel_slug)) or 0)


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
def post_chat_message(channel: LiveChannel, user, content: str) -> LiveChatMessage:
    if not channel.chat_enabled:
        raise ValueError("Le chat est desactive sur cette chaine.")
    if not channel.is_live:
        raise ValueError("Le chat n'est ouvert que pendant un direct.")

    session = channel.recordings.filter(ended_at__isnull=True).order_by(
        "-started_at"
    ).first()

    return LiveChatMessage.objects.create(
        live_channel=channel, session=session, user=user, content=content.strip()[:500]
    )


def recent_chat(channel: LiveChannel, limit: int = 50) -> list[LiveChatMessage]:
    """Backlog for a viewer joining mid-stream, scoped to the current session."""
    session = channel.recordings.filter(ended_at__isnull=True).order_by(
        "-started_at"
    ).first()
    queryset = LiveChatMessage.objects.filter(
        live_channel=channel, is_deleted=False
    ).select_related("user")
    if session is not None:
        queryset = queryset.filter(session=session)
    return list(queryset.order_by("-created_at")[:limit])[::-1]


# --------------------------------------------------------------------------
# Fan-out
# --------------------------------------------------------------------------
def broadcast(channel_slug: str, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover
        return
    try:
        async_to_sync(layer.group_send)(chat_group(channel_slug), payload)
    except Exception:
        logger.warning("live: broadcast failed for %s", channel_slug, exc_info=True)
