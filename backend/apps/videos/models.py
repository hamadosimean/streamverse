"""Video catalogue, renditions, thumbnails and the resumable-upload session.

Object-key layout in MinIO (one tree per video, so visibility changes move a
single prefix and deletes are one call):

    videos/<video_id>/hls/master.m3u8
    videos/<video_id>/hls/<label>/index.m3u8
    videos/<video_id>/hls/<label>/seg_0000.ts ...
    videos/<video_id>/thumbs/poster.jpg
    videos/<video_id>/thumbs/sprite.jpg
    videos/<video_id>/thumbs/thumbnails.vtt

The uploaded original always lives in the PRIVATE bucket under
`originals/<video_id>/source.<ext>` regardless of visibility — it is only ever
read by the worker (retry, live-recording conversion), never by a browser.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class VideoStatus(models.TextChoices):
    PROCESSING = "processing", _("En traitement")
    READY = "ready", _("Prete")
    FAILED = "failed", _("Echec")
    TAKEN_DOWN = "taken_down", _("Retiree")


class Visibility(models.TextChoices):
    PUBLIC = "public", _("Publique")
    UNLISTED = "unlisted", _("Non repertoriee")
    PRIVATE = "private", _("Privee")


class ProcessingStage(models.TextChoices):
    """Fine-grained stage inside `status=processing`, streamed to the uploader
    over WebSocket so the progress bar means something."""

    QUEUED = "queued", _("En file d'attente")
    PROBING = "probing", _("Analyse du fichier")
    TRANSCODING = "transcoding", _("Transcodage")
    PACKAGING = "packaging", _("Assemblage du manifeste")
    THUMBNAILS = "thumbnails", _("Generation des miniatures")
    PUBLISHING = "publishing", _("Publication")
    DONE = "done", _("Termine")


class VideoQuerySet(models.QuerySet):
    def ready(self):
        return self.filter(status=VideoStatus.READY)

    def publicly_listed(self):
        """Everything that may appear in feeds, search and category browsing.

        Unlisted videos are deliberately excluded: they are reachable by direct
        link only.
        """
        return self.filter(status=VideoStatus.READY, visibility=Visibility.PUBLIC,
                           uploader__is_suspended=False)

    def shorts(self):
        return self.publicly_listed().filter(is_short=True)

    def long_form(self):
        """The main catalogue, with Shorts held back.

        Shorts have their own full-screen surface; mixing a 15-second vertical
        clip into a grid of landscape thumbnails makes both look wrong, and it
        lets a flood of cheap short uploads bury everything else.
        """
        return self.publicly_listed().filter(is_short=False)

    def visible_to(self, user):
        """Rows a given viewer is allowed to *fetch by id*.

        Unlisted is included — holding the URL is the access control. Private is
        owner/staff only.
        """
        qs = self.exclude(status=VideoStatus.TAKEN_DOWN)
        if user is None or not user.is_authenticated:
            return qs.filter(status=VideoStatus.READY,
                             visibility__in=[Visibility.PUBLIC, Visibility.UNLISTED],
                             uploader__is_suspended=False)
        if user.is_staff_member:
            return self.all()
        return qs.filter(
            models.Q(uploader=user)
            | models.Q(status=VideoStatus.READY,
                       visibility__in=[Visibility.PUBLIC, Visibility.UNLISTED],
                       uploader__is_suspended=False)
        )

    def with_related(self):
        return self.select_related("uploader", "category").prefetch_related("tags")


class Video(UUIDPrimaryKeyModel, TimeStampedModel):
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="videos"
    )
    title = models.CharField(_("titre"), max_length=200)
    description = models.TextField(_("description"), max_length=5000, blank=True)

    status = models.CharField(
        max_length=16, choices=VideoStatus.choices,
        default=VideoStatus.PROCESSING, db_index=True,
    )
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices,
        default=Visibility.PRIVATE, db_index=True,
        help_text=_("Par defaut privee: rien n'est publie tant que l'auteur "
                    "n'a pas explicitement choisi de publier."),
    )

    category = models.ForeignKey(
        "catalog.Category", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="videos",
    )
    tags = models.ManyToManyField("catalog.Tag", blank=True, related_name="videos")

    # -- Source characteristics (filled by ffprobe) ------------------------
    duration_seconds = models.PositiveIntegerField(default=0, db_index=True)
    source_width = models.PositiveIntegerField(default=0)
    source_height = models.PositiveIntegerField(default=0)
    source_resolution = models.CharField(max_length=20, blank=True)
    source_video_codec = models.CharField(max_length=40, blank=True)
    source_audio_codec = models.CharField(max_length=40, blank=True)
    has_audio = models.BooleanField(default=True)

    # -- Original file ------------------------------------------------------
    original_key = models.CharField(max_length=512, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    original_size_bytes = models.BigIntegerField(default=0)
    original_mime_type = models.CharField(max_length=100, blank=True)

    # -- Derived assets -----------------------------------------------------
    storage_bucket = models.CharField(
        max_length=100, blank=True,
        help_text=_("Bucket ou vivent actuellement les rendus HLS. "
                    "Change quand la visibilite bascule prive <-> public."),
    )
    hls_master_path = models.CharField(max_length=512, blank=True)
    poster_path = models.CharField(max_length=512, blank=True)
    sprite_path = models.CharField(max_length=512, blank=True)
    thumbnail_vtt_path = models.CharField(max_length=512, blank=True)
    sprite_meta = models.JSONField(
        default=dict, blank=True,
        help_text=_("Geometrie de la planche de miniatures (colonnes, lignes, "
                    "taille de tuile, intervalle). Le lecteur calcule les "
                    "decalages a partir de ces valeurs, ce qui fonctionne a "
                    "l'identique pour les URLs publiques et presignees."),
    )

    # -- Pipeline state -----------------------------------------------------
    processing_stage = models.CharField(
        max_length=20, choices=ProcessingStage.choices, default=ProcessingStage.QUEUED
    )
    processing_progress = models.PositiveSmallIntegerField(
        default=0, help_text=_("0-100, tous stades confondus.")
    )
    failure_reason = models.TextField(blank=True)
    transcode_attempts = models.PositiveSmallIntegerField(default=0)

    # -- Engagement counters (denormalised; populated in Phase 3) -----------
    view_count = models.PositiveIntegerField(default=0, db_index=True)
    like_count = models.PositiveIntegerField(default=0)
    dislike_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)

    # -- Moderation ---------------------------------------------------------
    takedown_reason = models.TextField(blank=True)
    taken_down_at = models.DateTimeField(null=True, blank=True)

    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # -- Shorts -------------------------------------------------------------
    is_short = models.BooleanField(
        default=False, db_index=True,
        help_text=_("Format court vertical. Derive automatiquement de la duree "
                    "et du ratio de la source au moment du transcodage — jamais "
                    "saisi a la main, pour qu'une video ne puisse pas se declarer "
                    "short et court-circuiter le fil principal."),
    )

    # -- Full-text search ---------------------------------------------------
    search_vector = SearchVectorField(
        null=True, blank=True, editable=False,
        help_text=_("tsvector pondere (titre A, tags B, description C). "
                    "Maintenu par apps.search.services.update_search_vector."),
    )

    objects = VideoQuerySet.as_manager()

    class Meta:
        verbose_name = _("video")
        verbose_name_plural = _("videos")
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=["status", "visibility", "-published_at"]),
            models.Index(fields=["uploader", "-uploaded_at"]),
            models.Index(fields=["-view_count"]),
            # Without this, every search degrades to a sequential scan over the
            # whole catalogue.
            GinIndex(fields=["search_vector"], name="video_search_vector_gin"),
            # The Shorts feed filters on this every request.
            models.Index(fields=["is_short", "status", "visibility", "-published_at"],
                         name="video_shorts_feed_idx"),
        ]

    def __str__(self):
        return self.title

    # -- Derived properties -------------------------------------------------
    @property
    def asset_prefix(self) -> str:
        """The single MinIO prefix holding every derived asset for this video."""
        return f"videos/{self.id}"

    @property
    def is_public_asset(self) -> bool:
        """Public and unlisted assets both live in the public-read bucket.

        Unlisted security comes from the unguessable UUID in the URL, not from a
        signature — matching the spec's bucket split.
        """
        return self.visibility in (Visibility.PUBLIC, Visibility.UNLISTED)

    @property
    def target_bucket(self) -> str:
        return (settings.MINIO_PUBLIC_BUCKET if self.is_public_asset
                else settings.MINIO_PRIVATE_BUCKET)

    @property
    def is_playable(self) -> bool:
        return self.status == VideoStatus.READY and bool(self.hls_master_path)

    @property
    def aspect_ratio(self) -> float:
        """Width / height. 0 when the source was never probed."""
        return (self.source_width / self.source_height) if self.source_height else 0.0

    @property
    def is_portrait(self) -> bool:
        return bool(self.source_height and self.source_height > self.source_width)

    def qualifies_as_short(self) -> bool:
        """Both conditions, not either.

        A 20-second landscape clip is a short *video*, not a Short: the format is
        defined by the vertical frame as much as the length, and putting
        letterboxed 16:9 content into a full-screen portrait feed looks broken.
        Square is allowed — phones produce it and it fills the frame acceptably.
        """
        from django.conf import settings

        if not self.duration_seconds or not self.source_height:
            return False
        if self.duration_seconds > settings.SHORTS_MAX_DURATION_SECONDS:
            return False
        return self.aspect_ratio <= settings.SHORTS_MAX_ASPECT_RATIO

    def mark_failed(self, reason: str) -> None:
        self.status = VideoStatus.FAILED
        self.failure_reason = reason[:4000]
        self.processing_stage = ProcessingStage.QUEUED
        self.processing_progress = 0
        self.save(update_fields=["status", "failure_reason", "processing_stage",
                                 "processing_progress", "updated_at"])


class VideoRendition(models.Model):
    """One ABR ladder rung. Never upscales past the source (see services/ladder.py)."""

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="renditions")
    label = models.CharField(max_length=10, help_text="240p, 360p, 480p, 720p, 1080p")
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    video_bitrate_kbps = models.PositiveIntegerField()
    audio_bitrate_kbps = models.PositiveIntegerField(default=128)
    hls_playlist_path = models.CharField(max_length=512)
    file_size = models.BigIntegerField(default=0)
    segment_count = models.PositiveIntegerField(default=0)
    codecs = models.CharField(max_length=60, blank=True,
                              help_text="RFC 6381 string used in the master playlist.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("rendu video")
        verbose_name_plural = _("rendus video")
        ordering = ("height",)
        constraints = [
            models.UniqueConstraint(fields=("video", "label"),
                                    name="uniq_rendition_per_video_label"),
        ]

    def __str__(self):
        return f"{self.video_id} @ {self.label}"

    @property
    def bandwidth(self) -> int:
        """Total bits/s advertised in the master playlist (video + audio + overhead)."""
        return int((self.video_bitrate_kbps + self.audio_bitrate_kbps) * 1000 * 1.08)


class VideoThumbnail(models.Model):
    """Poster frame plus scrubbing-preview tiles.

    Tile rows record their offset into the sprite sheet so the player can build a
    WebVTT-equivalent index client-side if it wants; the generated `.vtt` file is
    what hls.js-adjacent seek-bar previews actually consume.
    """

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="thumbnails")
    timestamp_offset = models.FloatField(default=0, help_text=_("Secondes depuis le debut."))
    image_path = models.CharField(max_length=512)
    is_poster = models.BooleanField(default=False, db_index=True)
    # Sprite coordinates (null for the standalone poster).
    sprite_x = models.PositiveIntegerField(null=True, blank=True)
    sprite_y = models.PositiveIntegerField(null=True, blank=True)
    sprite_width = models.PositiveIntegerField(null=True, blank=True)
    sprite_height = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("miniature")
        verbose_name_plural = _("miniatures")
        ordering = ("timestamp_offset",)
        indexes = [models.Index(fields=["video", "timestamp_offset"])]

    def __str__(self):
        kind = "poster" if self.is_poster else f"t={self.timestamp_offset:.1f}s"
        return f"{self.video_id} {kind}"


class UploadStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", _("Televersement en cours")
    COMPLETED = "completed", _("Televersement termine")
    ABORTED = "aborted", _("Abandonne")
    EXPIRED = "expired", _("Expire")


class UploadSession(models.Model):
    """Server-side state for one tus resumable upload.

    Kept separate from `Video` on purpose: a `Video` row should mean "a video
    exists", and a half-transferred byte stream is not that. The `Video` is
    created only once the last chunk lands and validation passes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions"
    )
    filename = models.CharField(max_length=255)
    upload_length = models.BigIntegerField(help_text=_("Taille annoncee, en octets."))
    offset = models.BigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=UploadStatus.choices,
                              default=UploadStatus.IN_PROGRESS, db_index=True)

    # Client-supplied metadata carried through to the created Video.
    metadata = models.JSONField(default=dict, blank=True)

    scratch_path = models.CharField(max_length=512)
    video = models.OneToOneField(
        Video, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="upload_session",
    )
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = _("session de televersement")
        verbose_name_plural = _("sessions de televersement")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.filename} ({self.offset}/{self.upload_length})"

    @property
    def is_complete(self) -> bool:
        return self.offset >= self.upload_length
