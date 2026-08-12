"""Engagement API: views, likes, comments, reports."""
from __future__ import annotations

import logging

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.core.pagination import DefaultPagination
from apps.engagement import services
from apps.engagement.models import Comment, Like, Report
from apps.engagement.serializers import (
    CommentCreateSerializer,
    CommentSerializer,
    LikeStateSerializer,
    ReportCreateSerializer,
    ReportSerializer,
    ViewPingSerializer,
    ViewStateSerializer,
)
from apps.videos.models import Video

logger = logging.getLogger(__name__)


def get_watchable_video(request, video_id) -> Video:
    """A video the requester is allowed to see — the same gate playback uses."""
    user = request.user if request.user.is_authenticated else None
    return get_object_or_404(
        Video.objects.visible_to(user).select_related("uploader"), pk=video_id
    )


# --------------------------------------------------------------------------
# Views (watch tracking)
# --------------------------------------------------------------------------
@extend_schema(tags=["engagement"])
class VideoViewPingView(APIView):
    """Heartbeat from the player: `{watched_seconds, client_id}`.

    Anonymous callers are allowed — view counts should reflect everyone who
    watched, not only signed-in users. Deduplication and the minimum-watch-time
    threshold live in `services.register_view`, never on the client, so a crafted
    request cannot inflate a counter beyond one view per window.
    """

    permission_classes = [AllowAny]
    serializer_class = ViewPingSerializer

    @extend_schema(request=ViewPingSerializer, responses={200: ViewStateSerializer})
    def post(self, request, video_id):
        video = get_watchable_video(request, video_id)

        serializer = ViewPingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        watched = serializer.validated_data["watched_seconds"]
        view = services.register_view(
            video, request, watched_seconds=watched,
            client_id=serializer.validated_data.get("client_id", ""),
        )

        # The same heartbeat maintains the viewer's own history, so "recently
        # viewed" needs no extra request per playback.
        from apps.library.services import record_watch

        record_watch(user=request.user, video=video, progress_seconds=watched)
        video.refresh_from_db(fields=["view_count"])

        from apps.engagement.models import View as ViewModel

        return Response(
            {
                "counted": view.counted,
                "watched_seconds": view.watched_seconds,
                "required_seconds": ViewModel.required_seconds(video.duration_seconds),
                "view_count": video.view_count,
            }
        )


# --------------------------------------------------------------------------
# Likes
# --------------------------------------------------------------------------
@extend_schema(tags=["engagement"])
class VideoReactionView(APIView):
    """`GET` the caller's reaction, `POST` to set or toggle it.

    Body: `{"reaction": "like" | "dislike" | null}`. Sending the reaction that is
    already set clears it, which is what makes the button behave as a toggle.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LikeStateSerializer

    @extend_schema(responses={200: LikeStateSerializer})
    def get(self, request, video_id):
        video = get_watchable_video(request, video_id)
        existing = Like.objects.filter(video=video, user=request.user).first()
        return Response(
            {
                "my_reaction": (None if existing is None
                                else "like" if existing.is_like else "dislike"),
                "like_count": video.like_count,
                "dislike_count": video.dislike_count,
            }
        )

    @extend_schema(request=None, responses={200: LikeStateSerializer})
    def post(self, request, video_id):
        video = get_watchable_video(request, video_id)

        reaction = request.data.get("reaction")
        if reaction not in ("like", "dislike", None):
            raise ValidationError(
                {"reaction": "Valeur attendue: 'like', 'dislike' ou null."}
            )

        is_like = None if reaction is None else (reaction == "like")
        return Response(services.set_reaction(video, request.user, is_like))


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------
@extend_schema(tags=["engagement"])
class VideoCommentListCreateView(ListAPIView):
    """Threaded comments for one video: top-level nodes with their replies."""

    permission_classes = [AllowAny]
    serializer_class = CommentSerializer
    pagination_class = DefaultPagination

    def get_video(self):
        if not hasattr(self, "_video"):
            self._video = get_watchable_video(self.request, self.kwargs["video_id"])
        return self._video

    def get_queryset(self):
        # Schema generation instantiates the view without URL kwargs, so
        # `get_video()` would raise on the missing `video_id`.
        if getattr(self, "swagger_fake_view", False):
            return Comment.objects.none()

        video = self.get_video()
        # Replies are prefetched into `visible_replies`, which the serializer
        # reads — without this each top-level comment would trigger its own query.
        visible_replies = Prefetch(
            "replies",
            queryset=Comment.objects.select_related("author").order_by("created_at"),
            to_attr="visible_replies",
        )
        return (
            Comment.objects.filter(video=video, parent_comment__isnull=True)
            .select_related("author")
            .prefetch_related(visible_replies)
            .order_by("-created_at")
        )

    @extend_schema(request=CommentCreateSerializer, responses={201: CommentSerializer})
    def post(self, request, video_id):
        if not request.user.is_authenticated:
            raise PermissionDenied("Connectez-vous pour commenter.")

        video = self.get_video()
        serializer = CommentCreateSerializer(
            data=request.data, context={"request": request, "video": video}
        )
        serializer.is_valid(raise_exception=True)

        comment = services.create_comment(
            video=video,
            author=request.user,
            content=serializer.validated_data["content"],
            parent=serializer.validated_data.get("parent_comment"),
        )
        return Response(
            CommentSerializer(comment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def get_throttles(self):
        # Rate-limit writes only; reading a comment thread is not abuse.
        if self.request.method == "POST":
            self.throttle_scope = "comment"
        else:
            self.throttle_scope = None
        return super().get_throttles()


@extend_schema(tags=["engagement"])
class CommentDetailView(APIView):
    """Edit or soft-delete a single comment."""

    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def get_comment(self, comment_id) -> Comment:
        return get_object_or_404(
            Comment.objects.select_related("author", "video", "video__uploader"),
            pk=comment_id,
        )

    @extend_schema(request=CommentCreateSerializer, responses={200: CommentSerializer})
    def patch(self, request, comment_id):
        comment = self.get_comment(comment_id)
        # Only the author edits text. An uploader or moderator can remove a
        # comment but must never be able to put words in someone's mouth.
        if comment.author_id != request.user.pk:
            raise PermissionDenied("Vous ne pouvez modifier que vos commentaires.")
        if comment.is_deleted:
            raise ValidationError({"detail": "Ce commentaire a ete supprime."})

        serializer = CommentCreateSerializer(
            data={"content": request.data.get("content", ""),
                  "parent_comment": comment.parent_comment_id},
            context={"request": request, "video": comment.video},
        )
        serializer.is_valid(raise_exception=True)
        comment.content = serializer.validated_data["content"]
        comment.save(update_fields=["content", "updated_at"])

        return Response(CommentSerializer(comment, context={"request": request}).data)

    @extend_schema(responses={204: None})
    def delete(self, request, comment_id):
        comment = self.get_comment(comment_id)

        is_author = comment.author_id == request.user.pk
        is_uploader = comment.video.uploader_id == request.user.pk
        if not (is_author or is_uploader or request.user.is_staff_member):
            raise PermissionDenied("Vous ne pouvez pas supprimer ce commentaire.")

        reason = request.data.get("reason", "") if isinstance(request.data, dict) else ""
        services.delete_comment(comment, actor=request.user, reason=reason)

        # A removal by anyone other than the author is a moderation act.
        if not is_author:
            audit.record(
                AuditAction.COMMENT_REMOVED, actor=request.user, target=comment,
                reason=reason or "Suppression par le proprietaire ou un moderateur.",
                metadata={"video_id": str(comment.video_id)}, request=request,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@extend_schema(tags=["engagement"])
class ReportCreateView(APIView):
    """File a report against a video or comment.

    This is also the platform's copyright-takedown entry point. It is manual by
    design — there is no automated content-ID matching, and the README says so
    rather than implying otherwise.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ReportCreateSerializer

    @extend_schema(request=ReportCreateSerializer, responses={201: ReportSerializer})
    def post(self, request):
        serializer = ReportCreateSerializer(data=request.data,
                                            context={"request": request})
        serializer.is_valid(raise_exception=True)
        report = serializer.save()

        logger.info("report filed by %s: %s %s", request.user.username,
                    report.reason, report.object_id)
        return Response(
            ReportSerializer(report, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["engagement"])
class MyReportsView(ListAPIView):
    """Reports the caller filed, so they can see what happened to them."""

    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer

    def get_queryset(self):
        # Schema generation runs with an AnonymousUser, which cannot be used in
        # a FK filter.
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()
        return (
            Report.objects.filter(reporter=self.request.user)
            .select_related("content_type", "reporter")
            .order_by("-created_at")
        )


@extend_schema(tags=["engagement"])
class ReportReasonsView(APIView):
    """The report-reason vocabulary, so the client never hardcodes it."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from apps.engagement.models import ReportReason

        return Response(
            {"reasons": [{"value": value, "label": label}
                         for value, label in ReportReason.choices]}
        )
