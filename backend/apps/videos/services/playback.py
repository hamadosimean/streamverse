"""Playback URL resolution — the public / private delivery split.

The invariant this module exists to protect: **Django is never in the request
path for a video byte.**

Public and unlisted
    Renditions live in the public-read MinIO bucket. The API hands the player a
    plain MinIO URL and steps out of the way entirely. Every manifest and every
    segment is fetched browser -> MinIO. Unlisted content is protected by the
    unguessable UUID in the path, and the bucket policy grants `GetObject` only
    (never `ListBucket`), so the key space cannot be enumerated.

Private
    Renditions live in the private bucket. Authorisation happens **once per
    playback session**: `POST /api/videos/<id>/playback/` checks the viewer, then
    issues a signed session token. The player then fetches manifests from Django
    (kilobytes of text, generated on the fly with presigned segment URLs baked
    in) and every actual segment straight from MinIO.

    A 20-minute private video is roughly 300 segments per rendition. Proxying
    those through Django would mean 300 authenticated round-trips through the
    ASGI worker pool per viewer; this design costs 2-3 text responses instead.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.urls import reverse

from apps.core import storage
from apps.videos.models import Video
from apps.videos.services.packaging import rewrite_variant_playlist

logger = logging.getLogger(__name__)

PLAYBACK_TOKEN_SALT = "streamverse.playback"


class PlaybackDenied(Exception):
    pass


# --------------------------------------------------------------------------
# Session tokens (private videos only)
# --------------------------------------------------------------------------
def issue_playback_token(video: Video, user) -> str:
    """Bind a playback session to (video, viewer).

    Signed rather than stored: it is short-lived and carries no authority beyond
    reading manifests for one video, so a database round-trip per manifest fetch
    would buy nothing.
    """
    return signing.dumps(
        {"v": str(video.pk), "u": user.pk if user and user.is_authenticated else None},
        salt=PLAYBACK_TOKEN_SALT,
    )


def verify_playback_token(token: str, video_id) -> dict:
    try:
        payload = signing.loads(
            token, salt=PLAYBACK_TOKEN_SALT, max_age=session_ttl()
        )
    except signing.SignatureExpired as exc:
        raise PlaybackDenied("Session de lecture expiree.") from exc
    except signing.BadSignature as exc:
        raise PlaybackDenied("Jeton de lecture invalide.") from exc

    if payload.get("v") != str(video_id):
        raise PlaybackDenied("Jeton de lecture invalide pour cette video.")
    return payload


def session_ttl() -> int:
    return settings.MINIO_PRESIGN_TTL_SECONDS


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------
def can_watch(video: Video, user) -> bool:
    """Authorisation for playback. Called once per session, not per segment."""
    from apps.videos.models import VideoStatus, Visibility

    if video.status == VideoStatus.TAKEN_DOWN:
        return False
    if user and user.is_authenticated:
        if video.uploader_id == user.pk or user.is_staff_member:
            return True
    if video.status != VideoStatus.READY:
        return False
    if video.uploader.is_suspended:
        return False
    return video.visibility in (Visibility.PUBLIC, Visibility.UNLISTED)


def build_playback_payload(video: Video, user, request=None) -> dict:
    """Everything the player needs to start, in one response."""
    if not can_watch(video, user):
        raise PlaybackDenied("Vous n'avez pas acces a cette video.")
    if not video.is_playable:
        raise PlaybackDenied("Cette video n'est pas encore disponible.")

    renditions = [
        {
            "label": r.label,
            "width": r.width,
            "height": r.height,
            "bandwidth": r.bandwidth,
        }
        for r in video.renditions.all()
    ]

    if video.is_public_asset:
        payload = {
            "delivery": "public",
            "master_url": storage.public_url(video.hls_master_path),
            "poster_url": storage.public_url(video.poster_path) if video.poster_path else None,
            "sprite_url": storage.public_url(video.sprite_path) if video.sprite_path else None,
            "thumbnails_vtt_url": (
                storage.public_url(video.thumbnail_vtt_path)
                if video.thumbnail_vtt_path else None
            ),
            "expires_in": None,
        }
    else:
        token = issue_playback_token(video, user)
        master_path = reverse("videos:hls-master", kwargs={"video_id": video.pk})
        base = request.build_absolute_uri(master_path) if request else master_path
        payload = {
            "delivery": "signed",
            "master_url": f"{base}?token={quote(token)}",
            "poster_url": (storage.presigned_url(video.poster_path,
                                                 bucket=video.storage_bucket)
                           if video.poster_path else None),
            "sprite_url": (storage.presigned_url(video.sprite_path,
                                                 bucket=video.storage_bucket)
                           if video.sprite_path else None),
            # The static VTT points at a relative sprite filename that a signed
            # session cannot resolve; the player uses `sprite_meta` instead.
            "thumbnails_vtt_url": None,
            "expires_in": session_ttl(),
        }

    payload.update(
        {
            "video_id": str(video.pk),
            "duration_seconds": video.duration_seconds,
            "renditions": renditions,
            "sprite_meta": video.sprite_meta or None,
        }
    )
    return payload


# --------------------------------------------------------------------------
# Signed manifest generation (private videos)
# --------------------------------------------------------------------------
def signed_master_playlist(video: Video, token: str, request=None) -> str:
    """Master playlist whose variant entries route back through Django.

    The variants must stay Django-served because their *contents* are what carry
    the presigned segment URLs.
    """
    text = storage.get_text(video.storage_bucket, video.hls_master_path)

    def variant_url(rel_path: str) -> str:
        label = rel_path.split("/", 1)[0]
        path = reverse("videos:hls-variant",
                       kwargs={"video_id": video.pk, "label": label})
        absolute = request.build_absolute_uri(path) if request else path
        return f"{absolute}?token={quote(token)}"

    return rewrite_variant_playlist(text, variant_url)


def signed_variant_playlist(video: Video, label: str) -> str:
    """Variant playlist with every segment rewritten to a presigned MinIO URL.

    Presigning is local HMAC work — no network calls — so signing a few hundred
    segment URLs is sub-millisecond.
    """
    rendition = video.renditions.filter(label=label).first()
    if rendition is None:
        raise PlaybackDenied("Rendu introuvable.")

    text = storage.get_text(video.storage_bucket, rendition.hls_playlist_path)
    prefix = rendition.hls_playlist_path.rsplit("/", 1)[0]

    def segment_url(segment_name: str) -> str:
        return storage.presigned_url(
            f"{prefix}/{segment_name}",
            bucket=video.storage_bucket,
            ttl=session_ttl(),
        )

    return rewrite_variant_playlist(text, segment_url)
