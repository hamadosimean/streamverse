"""Moderation actions, centralised.

Every function here does the same three things in the same order: apply the
effect, write a `ModerationAction`, write an `AuditLog` entry. Nothing takes a
removal action without a reason — the check is repeated here even though the
serializer already validates it, because these functions are also called from
management commands and the admin.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.engagement.models import Comment, Report, ReportStatus
from apps.moderation.models import (
    ModerationAction,
    ModerationActionType,
    SanctionType,
    UserSanction,
)
from apps.videos.models import Video, VideoStatus

logger = logging.getLogger(__name__)

# Escalation threshold: this many upheld reports against a user's content in the
# window below is what "repeated violations" means in practice.
REPEAT_VIOLATION_THRESHOLD = 3
REPEAT_VIOLATION_WINDOW_DAYS = 90


class ModerationError(Exception):
    pass


def _require_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ModerationError(
            "Un motif d'au moins 10 caracteres est obligatoire: il est "
            "communique a l'auteur du contenu."
        )
    return reason


def _log(action: str, *, moderator, target, reason: str, report=None,
         affected_user=None, metadata=None, request=None) -> ModerationAction:
    entry = ModerationAction.objects.create(
        moderator=moderator,
        action=action,
        content_type=ContentType.objects.get_for_model(target.__class__)
        if target is not None else None,
        object_id=str(target.pk) if target is not None else "",
        target_repr=str(target)[:255] if target is not None else "",
        affected_user=affected_user,
        reason=reason,
        report=report,
        metadata=metadata or {},
    )
    return entry


# --------------------------------------------------------------------------
# Content actions
# --------------------------------------------------------------------------
@transaction.atomic
def take_down_video(video: Video, *, moderator, reason: str, report=None,
                    request=None) -> Video:
    """Remove a video from the platform.

    `taken_down` rather than a delete: the uploader is owed an explanation, an
    appeal needs the original, and a DMCA-style process needs a record of what
    was removed and why.
    """
    reason = _require_reason(reason)

    if video.status == VideoStatus.TAKEN_DOWN:
        raise ModerationError("Cette video est deja retiree.")

    video.status = VideoStatus.TAKEN_DOWN
    video.takedown_reason = reason
    video.taken_down_at = timezone.now()
    video.save(update_fields=["status", "takedown_reason", "taken_down_at",
                              "updated_at"])

    _log(ModerationActionType.VIDEO_TAKEN_DOWN, moderator=moderator, target=video,
         reason=reason, report=report, affected_user=video.uploader)
    audit.record(AuditAction.VIDEO_TAKEN_DOWN, actor=moderator, target=video,
                 reason=reason, metadata={"uploader": video.uploader.username},
                 request=request)

    logger.info("moderation: video %s taken down by %s", video.pk,
                moderator.username if moderator else "system")
    return video


@transaction.atomic
def restore_video(video: Video, *, moderator, reason: str, request=None) -> Video:
    """Reverse a takedown — an appeal succeeded, or the removal was a mistake."""
    reason = _require_reason(reason)

    if video.status != VideoStatus.TAKEN_DOWN:
        raise ModerationError("Cette video n'est pas retiree.")

    # Back to ready only if the assets are still there; otherwise the uploader
    # would get a playable-looking row with nothing behind it.
    video.status = VideoStatus.READY if video.hls_master_path else VideoStatus.FAILED
    video.takedown_reason = ""
    video.taken_down_at = None
    video.save(update_fields=["status", "takedown_reason", "taken_down_at",
                              "updated_at"])

    _log(ModerationActionType.VIDEO_RESTORED, moderator=moderator, target=video,
         reason=reason, affected_user=video.uploader)
    audit.record(AuditAction.VIDEO_TAKEN_DOWN, actor=moderator, target=video,
                 reason=f"RETABLIE: {reason}", request=request)
    return video


@transaction.atomic
def remove_comment(comment: Comment, *, moderator, reason: str, report=None,
                   request=None) -> Comment:
    reason = _require_reason(reason)

    if comment.is_deleted:
        raise ModerationError("Ce commentaire est deja supprime.")

    from apps.engagement.services import delete_comment

    delete_comment(comment, actor=moderator, reason=reason)

    _log(ModerationActionType.COMMENT_REMOVED, moderator=moderator, target=comment,
         reason=reason, report=report, affected_user=comment.author)
    audit.record(AuditAction.COMMENT_REMOVED, actor=moderator, target=comment,
                 reason=reason, request=request)
    return comment


# --------------------------------------------------------------------------
# Account actions
# --------------------------------------------------------------------------
@transaction.atomic
def suspend_user(user, *, moderator, reason: str, days: int | None = None,
                 permanent: bool = False, report=None, request=None) -> UserSanction:
    """Suspend or ban an account.

    Suspension takes effect on the *next request*, not the next login:
    `SuspensionAwareJWTAuthentication` rejects a suspended account even while it
    still holds an unexpired access token.
    """
    reason = _require_reason(reason)

    if user.is_staff_member:
        # A moderator suspending another moderator is a decision for an admin,
        # not a click in the queue.
        raise ModerationError(
            "Impossible de sanctionner un moderateur ou un administrateur "
            "depuis la file de moderation."
        )

    expires_at = None if permanent else timezone.now() + timedelta(days=days or 7)

    sanction = UserSanction.objects.create(
        user=user, moderator=moderator,
        type=SanctionType.BAN if permanent else SanctionType.SUSPENSION,
        reason=reason, expires_at=expires_at, report=report,
    )

    user.suspend(reason)

    _log(ModerationActionType.USER_SUSPENDED, moderator=moderator, target=user,
         reason=reason, report=report, affected_user=user,
         metadata={"permanent": permanent, "days": days,
                   "expires_at": expires_at.isoformat() if expires_at else None})
    audit.record(AuditAction.USER_SUSPENDED, actor=moderator, target=user,
                 reason=reason,
                 metadata={"permanent": permanent,
                           "expires_at": expires_at.isoformat() if expires_at else None},
                 request=request)

    logger.info("moderation: user %s suspended by %s (permanent=%s)",
                user.username, moderator.username if moderator else "system", permanent)
    return sanction


@transaction.atomic
def reinstate_user(user, *, moderator, reason: str, request=None):
    reason = _require_reason(reason)

    UserSanction.objects.filter(
        user=user, lifted_at__isnull=True,
        type__in=[SanctionType.SUSPENSION, SanctionType.BAN],
    ).update(lifted_at=timezone.now(), lifted_by=moderator)

    user.lift_suspension()

    _log(ModerationActionType.USER_REINSTATED, moderator=moderator, target=user,
         reason=reason, affected_user=user)
    audit.record(AuditAction.USER_UNSUSPENDED, actor=moderator, target=user,
                 reason=reason, request=request)
    return user


@transaction.atomic
def warn_user(user, *, moderator, reason: str, report=None, request=None) -> UserSanction:
    """Record a warning. Restricts nothing, but counts toward escalation."""
    reason = _require_reason(reason)

    sanction = UserSanction.objects.create(
        user=user, moderator=moderator, type=SanctionType.WARNING,
        reason=reason, report=report,
    )
    _log(ModerationActionType.USER_WARNED, moderator=moderator, target=user,
         reason=reason, report=report, affected_user=user)
    return sanction


# --------------------------------------------------------------------------
# Report resolution
# --------------------------------------------------------------------------
@transaction.atomic
def resolve_report(report: Report, *, moderator, action: str, reason: str = "",
                   suspend_days: int | None = None, request=None) -> Report:
    """Apply a decision to a report and close it.

    `action` is one of:
      `dismiss`          — the report was unfounded
      `remove`           — take the content down
      `remove_and_warn`  — take it down and record a warning
      `remove_and_suspend` — take it down and suspend the author
    """
    if report.status != ReportStatus.PENDING:
        raise ModerationError("Ce signalement a deja ete traite.")

    target = report.target
    if target is None and action != "dismiss":
        raise ModerationError(
            "La cible du signalement n'existe plus; seul un rejet est possible."
        )

    if action == "dismiss":
        report.status = ReportStatus.DISMISSED
        _log(ModerationActionType.REPORT_DISMISSED, moderator=moderator,
             target=target, reason=reason or "Signalement non fonde.",
             report=report)
    else:
        reason = _require_reason(reason)

        if isinstance(target, Video):
            take_down_video(target, moderator=moderator, reason=reason,
                            report=report, request=request)
            author = target.uploader
        elif isinstance(target, Comment):
            remove_comment(target, moderator=moderator, reason=reason,
                           report=report, request=request)
            author = target.author
        else:
            raise ModerationError("Type de contenu non pris en charge.")

        if action == "remove_and_warn":
            warn_user(author, moderator=moderator, reason=reason, report=report,
                      request=request)
        elif action == "remove_and_suspend":
            suspend_user(author, moderator=moderator, reason=reason,
                         days=suspend_days or 7, report=report, request=request)

        report.status = ReportStatus.ACTIONED

    report.reviewed_by = moderator
    report.reviewed_at = timezone.now()
    report.resolution_note = reason
    report.save(update_fields=["status", "reviewed_by", "reviewed_at",
                               "resolution_note", "updated_at"])

    # Other pending reports about the same thing are answered by this decision;
    # leaving them open would make a moderator review the same content again.
    siblings = Report.objects.filter(
        content_type=report.content_type, object_id=report.object_id,
        status=ReportStatus.PENDING,
    ).exclude(pk=report.pk)
    closed = siblings.update(
        status=report.status, reviewed_by=moderator, reviewed_at=timezone.now(),
        resolution_note=f"Traite avec le signalement #{report.pk}.",
    )

    audit.record(AuditAction.REPORT_REVIEWED, actor=moderator, target=report,
                 reason=reason,
                 metadata={"action": action, "status": report.status,
                           "also_closed": closed},
                 request=request)

    logger.info("moderation: report %s -> %s by %s (%d sibling(s) closed)",
                report.pk, action, moderator.username if moderator else "system",
                closed)
    return report


def user_violation_history(user, days: int = REPEAT_VIOLATION_WINDOW_DAYS) -> dict:
    """Context a moderator needs before deciding: has this happened before?"""
    since = timezone.now() - timedelta(days=days)

    actions = ModerationAction.objects.filter(
        affected_user=user, created_at__gte=since
    ).exclude(action__in=[ModerationActionType.VIDEO_RESTORED,
                          ModerationActionType.USER_REINSTATED,
                          ModerationActionType.REPORT_DISMISSED])

    return {
        "upheld_actions": actions.count(),
        "videos_taken_down": actions.filter(
            action=ModerationActionType.VIDEO_TAKEN_DOWN).count(),
        "comments_removed": actions.filter(
            action=ModerationActionType.COMMENT_REMOVED).count(),
        "warnings": UserSanction.objects.filter(
            user=user, type=SanctionType.WARNING, created_at__gte=since).count(),
        "suspensions": UserSanction.objects.filter(
            user=user, type__in=[SanctionType.SUSPENSION, SanctionType.BAN],
            created_at__gte=since).count(),
        "is_repeat_offender": actions.count() >= REPEAT_VIOLATION_THRESHOLD,
        "currently_suspended": user.is_suspended,
        "window_days": days,
    }
