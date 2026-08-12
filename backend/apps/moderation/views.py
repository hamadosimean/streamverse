"""Moderation API — the queue, decisions, sanctions and the admin dashboard.

Every endpoint here requires moderator or admin. The permission is checked
server-side; the frontend's role check only decides what to render.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin, IsModerator
from apps.engagement.models import Comment, Report, ReportStatus
from apps.moderation import services
from apps.moderation.models import ModerationAction, UserSanction
from apps.moderation.serializers import (
    ModerationActionSerializer,
    ModerationReportSerializer,
    ResolveReportSerializer,
    SanctionCreateSerializer,
    UserSanctionSerializer,
)
from apps.videos.models import Video, VideoStatus

logger = logging.getLogger(__name__)
User = get_user_model()


@extend_schema(tags=["moderation"])
class ReportQueueView(ListAPIView):
    """The moderation queue.

    Ordered oldest-first within a status: a queue that shows the newest report
    first is a queue where the oldest complaint never gets answered.
    """

    permission_classes = [IsAuthenticated, IsModerator]
    serializer_class = ModerationReportSerializer

    @extend_schema(parameters=[
        OpenApiParameter("status", str, description="pending | actioned | dismissed"),
        OpenApiParameter("reason", str),
        OpenApiParameter("target_type", str, description="video | comment"),
    ])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()

        queryset = Report.objects.select_related(
            "reporter", "reviewed_by", "content_type"
        )

        status_filter = self.request.query_params.get("status", "pending")
        if status_filter != "all":
            queryset = queryset.filter(status=status_filter)

        reason = self.request.query_params.get("reason")
        if reason:
            queryset = queryset.filter(reason=reason)

        target_type = self.request.query_params.get("target_type")
        if target_type in ("video", "comment"):
            queryset = queryset.filter(content_type__model=target_type)

        # Oldest first while pending; most recently decided first once closed.
        ordering = ("created_at",) if status_filter == "pending" else ("-reviewed_at",)
        return queryset.order_by(*ordering)


@extend_schema(tags=["moderation"])
class ReportDetailView(APIView):
    """One report, with the context needed to decide on it."""

    permission_classes = [IsAuthenticated, IsModerator]
    serializer_class = ModerationReportSerializer

    @extend_schema(responses={200: dict})
    def get(self, request, report_id):
        report = get_object_or_404(
            Report.objects.select_related("reporter", "reviewed_by", "content_type"),
            pk=report_id,
        )
        data = ModerationReportSerializer(report).data

        # How many other people reported the same thing — a strong signal, and
        # cheap to compute.
        data["duplicate_count"] = Report.objects.filter(
            content_type=report.content_type, object_id=report.object_id
        ).exclude(pk=report.pk).count()

        target = report.target
        author = None
        if isinstance(target, Video):
            author = target.uploader
        elif isinstance(target, Comment):
            author = target.author

        data["author_history"] = (
            services.user_violation_history(author) if author else None
        )
        data["recent_actions"] = ModerationActionSerializer(
            ModerationAction.objects.filter(affected_user=author)
            .select_related("moderator", "affected_user")
            .order_by("-created_at")[:5],
            many=True,
        ).data if author else []

        return Response(data)

    @extend_schema(request=ResolveReportSerializer,
                   responses={200: ModerationReportSerializer})
    def post(self, request, report_id):
        """Apply a decision and close the report."""
        report = get_object_or_404(Report, pk=report_id)

        serializer = ResolveReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            services.resolve_report(
                report,
                moderator=request.user,
                action=data["action"],
                reason=data.get("reason", ""),
                suspend_days=data.get("suspend_days"),
                request=request,
            )
        except services.ModerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        report.refresh_from_db()
        return Response(ModerationReportSerializer(report).data)


@extend_schema(tags=["moderation"])
class VideoModerationView(APIView):
    """Take down or restore a video directly, without going through a report."""

    permission_classes = [IsAuthenticated, IsModerator]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request, video_id):
        video = get_object_or_404(Video, pk=video_id)
        action = request.data.get("action")
        reason = request.data.get("reason", "")

        try:
            if action == "take_down":
                services.take_down_video(video, moderator=request.user,
                                         reason=reason, request=request)
            elif action == "restore":
                services.restore_video(video, moderator=request.user,
                                       reason=reason, request=request)
            else:
                raise ValidationError({"action": "Attendu: take_down ou restore."})
        except services.ModerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        video.refresh_from_db()
        return Response({"id": str(video.pk), "status": video.status,
                         "takedown_reason": video.takedown_reason})


@extend_schema(tags=["moderation"])
class SanctionView(APIView):
    """Warn, suspend, ban or reinstate an account."""

    permission_classes = [IsAuthenticated, IsModerator]
    serializer_class = SanctionCreateSerializer

    @extend_schema(request=SanctionCreateSerializer, responses={200: dict})
    def post(self, request):
        serializer = SanctionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target = get_object_or_404(User, username=data["username"])

        try:
            if data["action"] == "warn":
                services.warn_user(target, moderator=request.user,
                                   reason=data["reason"], request=request)
            elif data["action"] == "suspend":
                services.suspend_user(target, moderator=request.user,
                                      reason=data["reason"], days=data["days"],
                                      request=request)
            elif data["action"] == "ban":
                services.suspend_user(target, moderator=request.user,
                                      reason=data["reason"], permanent=True,
                                      request=request)
            else:
                services.reinstate_user(target, moderator=request.user,
                                        reason=data["reason"], request=request)
        except services.ModerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        target.refresh_from_db()
        return Response({
            "username": target.username,
            "is_suspended": target.is_suspended,
            "history": services.user_violation_history(target),
        })


@extend_schema(tags=["moderation"])
class UserModerationDetailView(APIView):
    """One user's moderation record — what a moderator checks before escalating."""

    permission_classes = [IsAuthenticated, IsModerator]

    @extend_schema(responses={200: dict})
    def get(self, request, username):
        target = get_object_or_404(User, username=username)
        return Response({
            "username": target.username,
            "display_name": target.display_name,
            "email": target.email if request.user.is_admin else None,
            "role": target.role,
            "is_suspended": target.is_suspended,
            "suspension_reason": target.suspension_reason,
            "joined": target.created_at,
            "history": services.user_violation_history(target),
            "sanctions": UserSanctionSerializer(
                target.sanctions.select_related("user", "moderator")
                .order_by("-created_at")[:20], many=True
            ).data,
            "actions": ModerationActionSerializer(
                ModerationAction.objects.filter(affected_user=target)
                .select_related("moderator", "affected_user")
                .order_by("-created_at")[:20], many=True
            ).data,
        })


@extend_schema(tags=["moderation"])
class ModerationLogView(ListAPIView):
    """Every decision taken, newest first. The moderator-facing audit trail."""

    permission_classes = [IsAuthenticated, IsModerator]
    serializer_class = ModerationActionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ModerationAction.objects.none()
        queryset = ModerationAction.objects.select_related(
            "moderator", "affected_user"
        )
        action = self.request.query_params.get("action")
        if action:
            queryset = queryset.filter(action=action)
        return queryset.order_by("-created_at")


@extend_schema(tags=["moderation"])
class ModerationStatsView(APIView):
    """Queue health: what is waiting, and how fast it is being cleared."""

    permission_classes = [IsAuthenticated, IsModerator]

    @extend_schema(responses={200: dict})
    def get(self, request):
        since = timezone.now() - timedelta(days=30)

        by_reason = list(
            Report.objects.filter(status=ReportStatus.PENDING)
            .values("reason").annotate(count=Count("id")).order_by("-count")
        )
        decisions_by_day = list(
            ModerationAction.objects.filter(created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(count=Count("id")).order_by("day")
        )

        oldest = Report.objects.filter(status=ReportStatus.PENDING).order_by(
            "created_at"
        ).first()

        return Response({
            "pending": Report.objects.filter(status=ReportStatus.PENDING).count(),
            "actioned": Report.objects.filter(status=ReportStatus.ACTIONED).count(),
            "dismissed": Report.objects.filter(status=ReportStatus.DISMISSED).count(),
            "pending_by_reason": by_reason,
            # Surfaced because a growing oldest-item age is the first sign a
            # moderation queue is failing, long before the total count looks bad.
            "oldest_pending_at": oldest.created_at if oldest else None,
            "decisions_30d": ModerationAction.objects.filter(
                created_at__gte=since).count(),
            "decisions_by_day": [
                {"date": row["day"].isoformat(), "count": row["count"]}
                for row in decisions_by_day
            ],
            "suspended_users": User.objects.filter(is_suspended=True).count(),
            "taken_down_videos": Video.objects.filter(
                status=VideoStatus.TAKEN_DOWN).count(),
        })


@extend_schema(tags=["admin"])
class AdminDashboardView(APIView):
    """Platform-wide numbers for the admin overview."""

    permission_classes = [IsAuthenticated, IsAdmin]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from apps.engagement.models import Comment as CommentModel
        from apps.live.models import LiveChannel, LiveStatus
        from apps.monetization.models import (
            AdCampaign,
            Transaction,
            TransactionStatus,
            UserSubscription,
        )
        from apps.videos.models import VideoRendition

        since = timezone.now() - timedelta(days=30)

        videos = Video.objects.aggregate(
            total=Count("id"),
            ready=Count("id", filter=Q(status=VideoStatus.READY)),
            processing=Count("id", filter=Q(status=VideoStatus.PROCESSING)),
            failed=Count("id", filter=Q(status=VideoStatus.FAILED)),
            taken_down=Count("id", filter=Q(status=VideoStatus.TAKEN_DOWN)),
            views=Sum("view_count"),
            duration=Sum("duration_seconds"),
        )
        storage = VideoRendition.objects.aggregate(total=Sum("file_size"))
        revenue = Transaction.objects.filter(
            status=TransactionStatus.COMPLETED
        ).aggregate(all_time=Sum("amount"),
                    last_30d=Sum("amount", filter=Q(completed_at__gte=since)))

        uploads_by_day = list(
            Video.objects.filter(uploaded_at__gte=since)
            .annotate(day=TruncDate("uploaded_at"))
            .values("day").annotate(count=Count("id")).order_by("day")
        )
        signups_by_day = list(
            User.objects.filter(created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(count=Count("id")).order_by("day")
        )

        return Response({
            "users": {
                "total": User.objects.count(),
                "active": User.objects.filter(is_active=True,
                                              is_suspended=False).count(),
                "suspended": User.objects.filter(is_suspended=True).count(),
                "moderators": User.objects.filter(role="moderator").count(),
                "new_30d": User.objects.filter(created_at__gte=since).count(),
            },
            "videos": {
                "total": videos["total"] or 0,
                "ready": videos["ready"] or 0,
                "processing": videos["processing"] or 0,
                "failed": videos["failed"] or 0,
                "taken_down": videos["taken_down"] or 0,
                "total_views": videos["views"] or 0,
                "total_duration_seconds": videos["duration"] or 0,
            },
            "storage": {
                # Renditions only: the archived originals live in the private
                # bucket and are not part of what is served.
                "renditions_bytes": storage["total"] or 0,
            },
            "engagement": {
                "comments": CommentModel.objects.filter(is_deleted=False).count(),
                "pending_reports": Report.objects.filter(
                    status=ReportStatus.PENDING).count(),
            },
            "live": {
                "channels": LiveChannel.objects.count(),
                "live_now": LiveChannel.objects.filter(
                    status=LiveStatus.LIVE).count(),
            },
            "monetization": {
                "active_subscriptions": UserSubscription.objects.active().count(),
                "revenue_all_time": revenue["all_time"] or 0,
                "revenue_30d": revenue["last_30d"] or 0,
                "active_campaigns": AdCampaign.objects.eligible().count(),
            },
            "uploads_by_day": [
                {"date": r["day"].isoformat(), "count": r["count"]}
                for r in uploads_by_day
            ],
            "signups_by_day": [
                {"date": r["day"].isoformat(), "count": r["count"]}
                for r in signups_by_day
            ],
        })
