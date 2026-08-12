"""Append-only audit trail.

Written for moderation actions, ad-campaign changes and payment/subscription
events (Phases 5-6), plus the ownership-sensitive video actions shipped in
Phase 2 (takedown, visibility change, retry).
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    # Videos
    VIDEO_UPLOADED = "video.uploaded", _("Video televersee")
    VIDEO_UPDATED = "video.updated", _("Video modifiee")
    VIDEO_DELETED = "video.deleted", _("Video supprimee")
    VIDEO_VISIBILITY_CHANGED = "video.visibility_changed", _("Visibilite modifiee")
    VIDEO_TRANSCODE_RETRIED = "video.transcode_retried", _("Transcodage relance")
    VIDEO_TAKEN_DOWN = "video.taken_down", _("Video retiree")
    # Accounts
    USER_SUSPENDED = "user.suspended", _("Compte suspendu")
    USER_UNSUSPENDED = "user.unsuspended", _("Suspension levee")
    USER_ROLE_CHANGED = "user.role_changed", _("Role modifie")
    # Live
    LIVE_KEY_ROTATED = "live.key_rotated", _("Cle de flux regeneree")
    LIVE_STARTED = "live.started", _("Direct demarre")
    LIVE_ENDED = "live.ended", _("Direct termine")
    # Engagement / moderation
    COMMENT_REMOVED = "comment.removed", _("Commentaire supprime")
    REPORT_REVIEWED = "report.reviewed", _("Signalement traite")
    # Reserved for later phases so the vocabulary stays in one place.
    CAMPAIGN_CHANGED = "campaign.changed", _("Campagne publicitaire modifiee")
    PAYMENT_EVENT = "payment.event", _("Evenement de paiement")


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_entries",
        help_text=_("Null pour les actions systeme (taches Celery)."),
    )
    action = models.CharField(max_length=64, choices=AuditAction.choices, db_index=True)

    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    target = GenericForeignKey("content_type", "object_id")

    # Human-readable snapshot: the target row may later be deleted.
    object_repr = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("entree d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        who = self.actor.username if self.actor else "systeme"
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.object_repr}"
