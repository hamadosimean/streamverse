"""Live streaming: channels, sessions, chat.

Ingest topology (see mediamtx/mediamtx.yml and the README):

    OBS ──RTMP──► MediaMTX :1935 ──► HLS :8888 ──► nginx /live-hls/ ──► viewer
                       │
                       ├─ auth hook   ──► Django validates the stream key
                       ├─ ready hook  ──► Django flips the channel to `live`
                       └─ record      ──► fMP4 on disk ──► Celery ──► VOD pipeline

**The RTMP path is the public channel slug; the stream key travels in the query
string.** That split matters: the HLS URL viewers fetch contains the path, so
putting the secret there would hand it to every viewer.
"""
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


def generate_stream_key() -> str:
    """A stream key is a bearer credential for publishing — treat it like one."""
    return secrets.token_urlsafe(32)


class LiveStatus(models.TextChoices):
    OFFLINE = "offline", _("Hors ligne")
    LIVE = "live", _("En direct")
    ENDED = "ended", _("Termine")


class LiveChannel(TimeStampedModel):
    """One live channel per user.

    Separate from `Video` on purpose: a live stream has no renditions, no
    duration and no object-storage prefix until it ends and its recording goes
    through the VOD pipeline as a normal upload.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="live_channel"
    )
    slug = models.SlugField(
        max_length=40, unique=True, db_index=True,
        help_text=_("Identifiant public du direct. Apparait dans l'URL HLS: "
                    "il ne doit jamais contenir la cle de flux."),
    )

    title = models.CharField(_("titre"), max_length=200, blank=True)
    description = models.TextField(_("description"), max_length=2000, blank=True)
    category = models.ForeignKey(
        "catalog.Category", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="live_channels",
    )

    # -- Credentials --------------------------------------------------------
    stream_key = models.CharField(
        max_length=64, unique=True, default=generate_stream_key, editable=False,
        help_text=_("Secret. Jamais expose a personne d'autre que le proprietaire."),
    )
    stream_key_rotated_at = models.DateTimeField(default=timezone.now)

    # -- State --------------------------------------------------------------
    status = models.CharField(max_length=10, choices=LiveStatus.choices,
                              default=LiveStatus.OFFLINE, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    current_viewer_count = models.PositiveIntegerField(default=0)
    peak_viewer_count = models.PositiveIntegerField(
        default=0, help_text=_("Pic sur la session en cours ou la derniere session."),
    )
    all_time_peak_viewers = models.PositiveIntegerField(default=0)
    total_sessions = models.PositiveIntegerField(default=0)

    # -- Policy -------------------------------------------------------------
    is_enabled = models.BooleanField(
        default=True, db_index=True,
        help_text=_("Decoche par un moderateur pour bloquer toute nouvelle "
                    "diffusion sans supprimer la chaine."),
    )
    chat_enabled = models.BooleanField(default=True)
    record_sessions = models.BooleanField(
        default=True,
        help_text=_("Convertit l'enregistrement en video a la fin du direct."),
    )

    class Meta:
        verbose_name = _("chaine en direct")
        verbose_name_plural = _("chaines en direct")
        ordering = ("-started_at", "-created_at")
        indexes = [models.Index(fields=["status", "-started_at"])]

    def __str__(self):
        return f"{self.slug} ({self.get_status_display()})"

    @property
    def is_live(self) -> bool:
        return self.status == LiveStatus.LIVE

    @property
    def rtmp_path(self) -> str:
        """MediaMTX path. Public — the key is never part of it."""
        return f"{settings.LIVE_RTMP_APP}/{self.slug}"

    def rotate_stream_key(self) -> str:
        """Issue a new key and invalidate the old one immediately.

        A leaked key lets anyone publish as this channel, so rotation must take
        effect at once rather than at the next stream.
        """
        self.stream_key = generate_stream_key()
        self.stream_key_rotated_at = timezone.now()
        self.save(update_fields=["stream_key", "stream_key_rotated_at", "updated_at"])
        return self.stream_key


class LiveRecording(TimeStampedModel):
    """One live session, and the recording it produced.

    Doubles as the session record: chat messages hang off it so a new broadcast
    starts with a clean chat rather than yesterday's conversation.
    """

    live_channel = models.ForeignKey(
        LiveChannel, on_delete=models.CASCADE, related_name="recordings"
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    peak_viewer_count = models.PositiveIntegerField(default=0)
    chat_message_count = models.PositiveIntegerField(default=0)

    # Path on the shared recordings volume, written by MediaMTX.
    recorded_file = models.CharField(max_length=512, blank=True)
    recorded_size_bytes = models.BigIntegerField(default=0)

    converted_video = models.ForeignKey(
        "videos.Video", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="source_live_recording",
        help_text=_("Renseigne une fois l'enregistrement passe par le pipeline VOD."),
    )
    conversion_error = models.TextField(blank=True)

    class Meta:
        verbose_name = _("session en direct")
        verbose_name_plural = _("sessions en direct")
        ordering = ("-started_at",)
        indexes = [models.Index(fields=["live_channel", "-started_at"])]

    def __str__(self):
        return f"{self.live_channel.slug} @ {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration_seconds(self) -> int:
        end = self.ended_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds()))

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class LiveChatMessage(models.Model):
    """A chat message, scoped to one live session.

    Persisted rather than fire-and-forget: a viewer joining mid-stream gets the
    recent backlog instead of an empty box, and moderation needs the record.
    """

    live_channel = models.ForeignKey(
        LiveChannel, on_delete=models.CASCADE, related_name="chat_messages"
    )
    session = models.ForeignKey(
        LiveRecording, null=True, blank=True, on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="live_messages"
    )
    content = models.TextField(max_length=500)

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deleted_live_messages",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("message de chat")
        verbose_name_plural = _("messages de chat")
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["live_channel", "-created_at"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.content[:40]}"
