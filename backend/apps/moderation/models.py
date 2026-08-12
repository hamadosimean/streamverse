"""Moderation: decisions and sanctions.

The *queue* is `engagement.Report` — reports are what moderators work through,
and duplicating them here would mean two sources of truth for one workflow.
What lives here is the record of what was **decided**: which action was taken,
by whom, and on what stated grounds.

Two things are non-negotiable in this app:

* **A removal always carries a reason.** Enforced in the serializer and again in
  the service, because "content disappeared and nobody can say why" is how a
  moderation system loses the trust of the people it moderates.
* **Every decision is audited.** `AuditLog` gets an entry for each one; these
  rows are the moderator-facing view of the same history.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class ModerationActionType(models.TextChoices):
    VIDEO_TAKEN_DOWN = "video_taken_down", _("Video retiree")
    VIDEO_RESTORED = "video_restored", _("Video retablie")
    COMMENT_REMOVED = "comment_removed", _("Commentaire supprime")
    REPORT_DISMISSED = "report_dismissed", _("Signalement rejete")
    USER_WARNED = "user_warned", _("Utilisateur averti")
    USER_SUSPENDED = "user_suspended", _("Utilisateur suspendu")
    USER_REINSTATED = "user_reinstated", _("Utilisateur retabli")
    LIVE_CHANNEL_DISABLED = "live_disabled", _("Chaine en direct desactivee")
    LIVE_CHANNEL_ENABLED = "live_enabled", _("Chaine en direct reactivee")


class ModerationAction(TimeStampedModel):
    """One decision, immutable once written."""

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="moderation_actions",
    )
    action = models.CharField(max_length=24, choices=ModerationActionType.choices,
                              db_index=True)

    content_type = models.ForeignKey(ContentType, null=True, blank=True,
                                     on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    target = GenericForeignKey("content_type", "object_id")
    target_repr = models.CharField(max_length=255, blank=True)

    # The owner of the content acted on — lets a moderator see someone's history
    # without joining through three tables.
    affected_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="moderation_history",
    )

    reason = models.TextField(
        help_text=_("Obligatoire pour toute action de retrait. C'est ce texte "
                    "qui est communique a l'auteur du contenu."),
    )
    report = models.ForeignKey(
        "engagement.Report", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="moderation_actions",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("action de moderation")
        verbose_name_plural = _("actions de moderation")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["affected_user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        who = self.moderator.username if self.moderator else "systeme"
        return f"{who}: {self.get_action_display()} -> {self.target_repr}"


class SanctionType(models.TextChoices):
    WARNING = "warning", _("Avertissement")
    SUSPENSION = "suspension", _("Suspension temporaire")
    BAN = "ban", _("Bannissement definitif")


class UserSanction(TimeStampedModel):
    """A warning, suspension or ban against an account.

    Kept as history rather than only a boolean on `User`: "repeated violations"
    is the stated trigger for escalation, and you cannot count repeats against a
    flag that gets overwritten.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="sanctions")
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="sanctions_issued",
    )
    type = models.CharField(max_length=12, choices=SanctionType.choices, db_index=True)
    reason = models.TextField()

    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text=_("Null pour un bannissement definitif ou un avertissement."),
    )
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sanctions_lifted",
    )

    report = models.ForeignKey(
        "engagement.Report", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sanctions",
    )

    class Meta:
        verbose_name = _("sanction")
        verbose_name_plural = _("sanctions")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.get_type_display()} — {self.user_id}"

    @property
    def is_active(self) -> bool:
        if self.lifted_at is not None:
            return False
        if self.type == SanctionType.WARNING:
            return False  # a warning restricts nothing; it is a record
        if self.expires_at is None:
            return True   # permanent ban
        return self.expires_at > timezone.now()
