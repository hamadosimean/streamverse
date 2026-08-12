"""Views, likes, comments and reports.

The counters denormalised onto `Video` (view_count, like_count, dislike_count,
comment_count) are maintained here with `F()` expressions so concurrent writes
cannot lose an increment, and are periodically reconciled against the source
rows by a beat task (`engagement.reconcile_counters`).
"""
from __future__ import annotations

import hashlib

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class View(models.Model):
    """One viewing session.

    A row is created per (video, identity, time-bucket) — not per page load — so
    refreshing a page fifteen times is one view, not fifteen. The row only
    *counts* toward `Video.view_count` once `watched_seconds` crosses the
    threshold in `qualifies()`, which is what stops a bounce from inflating the
    number.

    Anonymous viewers are tracked by an opaque client id plus a salted IP hash.
    That is deliberately weak identity: enough to deduplicate, not enough to
    build a profile. The raw IP is never stored.
    """

    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE,
                              related_name="views")
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="views",
        help_text=_("Null pour les visiteurs anonymes."),
    )
    session_key = models.CharField(max_length=64, blank=True)
    ip_hash = models.CharField(
        max_length=64, blank=True,
        help_text=_("SHA-256 sale de l'IP. L'IP brute n'est jamais stockee."),
    )

    watched_seconds = models.PositiveIntegerField(default=0)
    counted = models.BooleanField(
        default=False, db_index=True,
        help_text=_("Passe a True quand la duree minimale est atteinte."),
    )

    # Unique per (video, identity, time bucket) — see `build_dedup_key`.
    dedup_key = models.CharField(max_length=64, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("vue")
        verbose_name_plural = _("vues")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("video", "dedup_key"),
                                    name="uniq_view_per_video_dedup_key"),
        ]
        indexes = [
            models.Index(fields=["video", "counted", "-created_at"]),
            models.Index(fields=["viewer", "-created_at"]),
        ]

    def __str__(self):
        who = self.viewer.username if self.viewer else "anonyme"
        return f"{who} -> {self.video_id} ({self.watched_seconds}s)"

    # -- Dedup / qualification -------------------------------------------
    @staticmethod
    def build_dedup_key(video_id, identity: str, bucket: int) -> str:
        raw = f"{video_id}:{identity}:{bucket}:{settings.SECRET_KEY}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def hash_ip(ip: str | None) -> str:
        if not ip:
            return ""
        return hashlib.sha256(f"{ip}:{settings.SECRET_KEY}".encode()).hexdigest()

    @staticmethod
    def required_seconds(duration_seconds: int) -> int:
        """Minimum watch time before a view counts.

        30 seconds, or 30% of the video for anything shorter — a 10-second clip
        can never accumulate 30 seconds of watch time, so a flat threshold would
        make short videos permanently uncountable.
        """
        if duration_seconds <= 0:
            return settings.VIEW_MIN_SECONDS
        return max(1, min(settings.VIEW_MIN_SECONDS, int(duration_seconds * 0.3)))

    def qualifies(self) -> bool:
        return self.watched_seconds >= self.required_seconds(
            self.video.duration_seconds
        )


class Like(TimeStampedModel):
    """A like or a dislike. One row per (video, user); `is_like` distinguishes.

    Modelled as a single row rather than two tables so switching from like to
    dislike is an update, not a delete plus an insert that could interleave badly
    with the counter maintenance.
    """

    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE,
                              related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="likes")
    is_like = models.BooleanField(
        help_text=_("True = j'aime, False = je n'aime pas."),
    )

    class Meta:
        verbose_name = _("appreciation")
        verbose_name_plural = _("appreciations")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("video", "user"),
                                    name="uniq_like_per_video_user"),
        ]
        indexes = [models.Index(fields=["video", "is_like"])]

    def __str__(self):
        return f"{self.user_id} {'+1' if self.is_like else '-1'} {self.video_id}"


class Comment(TimeStampedModel):
    """A comment, or a reply to one. Exactly one level of nesting.

    Deletion is soft: removing the row would orphan its replies, and a moderator
    needs the original text to justify an action after the fact.
    """

    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE,
                              related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="comments")
    content = models.TextField(max_length=2000)
    parent_comment = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE,
        related_name="replies",
        help_text=_("Un seul niveau de reponse: une reponse ne peut pas avoir "
                    "elle-meme de parent."),
    )

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deleted_comments",
    )
    deletion_reason = models.TextField(blank=True)

    reply_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("commentaire")
        verbose_name_plural = _("commentaires")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["video", "parent_comment", "-created_at"]),
            models.Index(fields=["author", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.author_id}: {self.content[:40]}"

    @property
    def is_reply(self) -> bool:
        return self.parent_comment_id is not None

    def soft_delete(self, actor=None, reason: str = "") -> None:
        self.is_deleted = True
        self.deleted_by = actor
        self.deletion_reason = reason
        self.save(update_fields=["is_deleted", "deleted_by", "deletion_reason",
                                 "updated_at"])


class ReportReason(models.TextChoices):
    SPAM = "spam", _("Spam ou contenu trompeur")
    HARASSMENT = "harassment", _("Harcelement ou haine")
    VIOLENCE = "violence", _("Violence ou contenu choquant")
    SEXUAL = "sexual", _("Contenu sexuel")
    COPYRIGHT = "copyright", _("Violation de droits d'auteur")
    MISINFORMATION = "misinformation", _("Desinformation")
    OTHER = "other", _("Autre")


class ReportStatus(models.TextChoices):
    PENDING = "pending", _("En attente")
    ACTIONED = "actioned", _("Traite")
    DISMISSED = "dismissed", _("Rejete")


class Report(TimeStampedModel):
    """A user report against a video or a comment.

    Generic FK because the moderation queue is one list regardless of target
    type — a moderator works through reports, not through two parallel queues.

    This is also the platform's only copyright-takedown mechanism: it is manual,
    and the README says so. There is no automated content-ID matching.
    """

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="reports_filed")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64, db_index=True)
    target = GenericForeignKey("content_type", "object_id")

    reason = models.CharField(max_length=24, choices=ReportReason.choices)
    details = models.TextField(max_length=1000, blank=True)

    status = models.CharField(max_length=12, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reports_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        verbose_name = _("signalement")
        verbose_name_plural = _("signalements")
        ordering = ("-created_at",)
        constraints = [
            # One pending report per user per target: a user hammering the button
            # should not flood the moderation queue with duplicates.
            models.UniqueConstraint(
                fields=("reporter", "content_type", "object_id"),
                condition=models.Q(status="pending"),
                name="uniq_pending_report_per_reporter_target",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.get_reason_display()} -> {self.content_type} {self.object_id}"
