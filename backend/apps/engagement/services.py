"""Engagement write paths, centralised.

Every counter mutation lives here and uses `F()` expressions, so two concurrent
likes cannot read-modify-write over each other. The denormalised counters on
`Video` are a cache of these tables and are reconciled nightly by
`engagement.tasks.reconcile_counters`.
"""
from __future__ import annotations

import logging
import time

from django.db import transaction
from django.db.models import F, IntegerField, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.engagement.models import Comment, Like, View
from apps.videos.models import Video

logger = logging.getLogger(__name__)


def clamped(expression):
    """Clamp a counter expression at zero.

    The counters are PositiveIntegerFields; letting a decrement drive one
    negative raises an IntegrityError at the database level.
    """
    return Greatest(expression, Value(0), output_field=IntegerField())


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def viewer_identity(request, client_id: str = "") -> tuple[str, str]:
    """Resolve (identity, session_key) for view deduplication.

    Authenticated users dedupe on their user id. Anonymous viewers dedupe on the
    opaque id their browser generated, falling back to the Django session key and
    then to a salted IP hash — each step weaker, but all we can do without
    identifying anyone.
    """
    if request.user.is_authenticated:
        return f"u{request.user.pk}", ""

    if client_id:
        return f"c{client_id}", client_id

    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key or ""
    if session_key:
        return f"s{session_key}", session_key

    return f"i{View.hash_ip(client_ip(request))}", ""


def register_view(video: Video, request, watched_seconds: int,
                  client_id: str = "") -> View:
    """Record or update a viewing session.

    Idempotent within the dedup window: repeated calls update the same row and
    increment `Video.view_count` at most once.
    """
    from django.conf import settings

    identity, session_key = viewer_identity(request, client_id)
    bucket = int(time.time() // settings.VIEW_DEDUP_WINDOW_SECONDS)
    dedup_key = View.build_dedup_key(video.pk, identity, bucket)

    with transaction.atomic():
        view, _created = View.objects.select_for_update().get_or_create(
            video=video,
            dedup_key=dedup_key,
            defaults={
                "viewer": request.user if request.user.is_authenticated else None,
                "session_key": session_key,
                "ip_hash": View.hash_ip(client_ip(request)),
            },
        )

        # Monotonic: a late or replayed ping must never reduce progress.
        if watched_seconds > view.watched_seconds:
            view.watched_seconds = watched_seconds

        newly_counted = False
        if not view.counted and view.qualifies():
            view.counted = True
            newly_counted = True

        view.save(update_fields=["watched_seconds", "counted", "updated_at"])

        if newly_counted:
            Video.objects.filter(pk=video.pk).update(
                view_count=F("view_count") + 1
            )
            logger.debug("view counted for %s (%ds)", video.pk, view.watched_seconds)

    return view


def set_reaction(video: Video, user, is_like: bool | None) -> dict:
    """Apply a like / dislike / clear, and return the resulting state.

    `is_like=None` removes the reaction. Re-sending the same value also removes
    it, which is what makes the button a toggle.
    """
    with transaction.atomic():
        existing = Like.objects.select_for_update().filter(
            video=video, user=user
        ).first()

        if is_like is None or (existing and existing.is_like == is_like):
            if existing:
                existing.delete()
            my_reaction = None
        elif existing:
            existing.is_like = is_like
            existing.save(update_fields=["is_like", "updated_at"])
            my_reaction = "like" if is_like else "dislike"
        else:
            Like.objects.create(video=video, user=user, is_like=is_like)
            my_reaction = "like" if is_like else "dislike"

        # Recount from the source rows inside the same transaction: cheap (the
        # index covers it) and immune to drift, unlike incremental deltas across
        # a like -> dislike switch.
        likes = Like.objects.filter(video=video, is_like=True).count()
        dislikes = Like.objects.filter(video=video, is_like=False).count()
        Video.objects.filter(pk=video.pk).update(
            like_count=likes, dislike_count=dislikes
        )

    return {"my_reaction": my_reaction, "like_count": likes,
            "dislike_count": dislikes}


def create_comment(video: Video, author, content: str, parent: Comment | None) -> Comment:
    with transaction.atomic():
        comment = Comment.objects.create(
            video=video, author=author, content=content, parent_comment=parent
        )
        Video.objects.filter(pk=video.pk).update(
            comment_count=F("comment_count") + 1
        )
        if parent is not None:
            Comment.objects.filter(pk=parent.pk).update(
                reply_count=F("reply_count") + 1
            )
    return comment


def delete_comment(comment: Comment, actor, reason: str = "") -> None:
    """Soft-delete a comment and its replies.

    Replies are deleted too: leaving them under a removed parent would strand a
    thread whose context is gone, and a moderator removing abuse expects the
    pile-on beneath it to go with it.
    """
    with transaction.atomic():
        if comment.is_deleted:
            return

        replies = list(comment.replies.filter(is_deleted=False))
        comment.soft_delete(actor=actor, reason=reason)
        for reply in replies:
            reply.soft_delete(actor=actor, reason="Commentaire parent supprime.")

        removed = 1 + len(replies)
        Video.objects.filter(pk=comment.video_id).update(
            comment_count=clamped(F("comment_count") - removed)
        )
        if comment.parent_comment_id:
            Comment.objects.filter(pk=comment.parent_comment_id).update(
                reply_count=clamped(F("reply_count") - 1)
            )


def mark_report_reviewed(report, moderator, status: str, note: str = ""):
    report.status = status
    report.reviewed_by = moderator
    report.reviewed_at = timezone.now()
    report.resolution_note = note
    report.save(update_fields=["status", "reviewed_by", "reviewed_at",
                               "resolution_note", "updated_at"])
    return report
