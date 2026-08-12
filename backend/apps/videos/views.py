"""Video API.

Split into three groups:

* **Public catalogue** — anonymous-readable list/detail of `ready` + `public`
  videos, plus by-id access to unlisted ones.
* **Playback** — the once-per-session authorisation, and the two Django-served
  manifest endpoints used only by private videos.
* **Studio** — the uploader's own videos. Every queryset here is filtered by
  `uploader=request.user` at the database level, so an object-level permission
  bug cannot expose someone else's row.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.core.permissions import IsOwner
from apps.videos.filters import VideoFilter
from apps.videos.models import Video, VideoStatus, Visibility
from apps.videos.serializers import (
    PlaybackSerializer,
    StudioStatsSerializer,
    StudioVideoSerializer,
    VideoCardSerializer,
    VideoDetailSerializer,
    VideoUpdateSerializer,
)
from apps.search.services import update_search_vector
from apps.videos.services import playback as playback_service
from apps.videos.tasks import (
    delete_video_assets,
    relocate_assets,
    start_transcoding_pipeline,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Public catalogue
# --------------------------------------------------------------------------
@extend_schema(tags=["videos"])
class VideoListView(ListAPIView):
    """Public feed. Only `ready` + `public` videos from non-suspended uploaders.

    Unlisted videos are excluded here by design — they are reachable by direct
    link only, which is the whole point of "unlisted".
    """

    permission_classes = [AllowAny]
    serializer_class = VideoCardSerializer
    filterset_class = VideoFilter

    ORDERINGS = {
        "recent": ("-published_at",),
        "trending": ("-view_count", "-published_at"),
        "oldest": ("published_at",),
        "longest": ("-duration_seconds",),
    }

    @extend_schema(parameters=[
        OpenApiParameter("sort", str, description="recent | trending | oldest | longest"),
    ])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        sort = self.request.query_params.get("sort", "recent")
        ordering = self.ORDERINGS.get(sort, self.ORDERINGS["recent"])
        return Video.objects.publicly_listed().with_related().order_by(*ordering)


@extend_schema(tags=["videos"])
class HomeFeedView(APIView):
    """Homepage feed: recent + trending, not personalised.

    Explicitly *not* a recommendation engine — see the README scope notes. Phase 3
    adds content-based related-videos on the watch page; personalised ML ranking
    is out of scope and is not silently approximated here.
    """

    permission_classes = [AllowAny]

    @extend_schema(responses={200: VideoCardSerializer(many=True)})
    def get(self, request):
        base = Video.objects.publicly_listed().with_related()
        context = {"request": request}
        since = timezone.now() - timedelta(days=30)

        return Response(
            {
                "recent": VideoCardSerializer(
                    base.order_by("-published_at")[:12], many=True, context=context
                ).data,
                "trending": VideoCardSerializer(
                    base.filter(published_at__gte=since)
                        .order_by("-view_count", "-published_at")[:12],
                    many=True, context=context,
                ).data,
                "most_viewed": VideoCardSerializer(
                    base.order_by("-view_count")[:12], many=True, context=context
                ).data,
            }
        )


@extend_schema(tags=["videos"])
class VideoDetailView(RetrieveAPIView):
    """Watch-page metadata. Visibility is enforced by the queryset, not by a
    post-hoc check on a globally-visible row."""

    permission_classes = [AllowAny]
    serializer_class = VideoDetailSerializer

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return Video.objects.visible_to(user).with_related()


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------
@extend_schema(tags=["playback"])
class PlaybackView(APIView):
    """Authorise a playback session and return everything the player needs.

    Called **once** per playback, never per segment. For public/unlisted videos
    the response points straight at MinIO. For private ones it returns a signed,
    short-lived manifest URL served by Django, whose contents carry presigned
    MinIO segment URLs.
    """

    permission_classes = [AllowAny]

    @extend_schema(responses={200: PlaybackSerializer}, request=None)
    def post(self, request, pk):
        video = self._get_video(request, pk)
        user = request.user if request.user.is_authenticated else None
        try:
            payload = playback_service.build_playback_payload(video, user, request)
        except playback_service.PlaybackDenied as exc:
            return Response({"detail": str(exc), "code": "playback_denied",
                             "errors": None}, status=status.HTTP_403_FORBIDDEN)
        return Response(payload)

    def _get_video(self, request, pk):
        user = request.user if request.user.is_authenticated else None
        from django.shortcuts import get_object_or_404

        return get_object_or_404(
            Video.objects.visible_to(user).select_related("uploader")
                 .prefetch_related("renditions"),
            pk=pk,
        )


class _SignedManifestView(APIView):
    """Base for the two Django-served manifest endpoints.

    Authentication is the playback token, not the JWT: hls.js fetches manifests
    with a bare XHR that carries no Authorization header. The token is signed,
    short-lived and scoped to one video.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def resolve(self, request, video_id):
        from django.shortcuts import get_object_or_404

        token = request.query_params.get("token", "")
        if not token:
            return None, Response({"detail": "Jeton de lecture manquant."},
                                  status=status.HTTP_401_UNAUTHORIZED)
        try:
            playback_service.verify_playback_token(token, video_id)
        except playback_service.PlaybackDenied as exc:
            return None, Response({"detail": str(exc)},
                                  status=status.HTTP_403_FORBIDDEN)

        video = get_object_or_404(Video.objects.prefetch_related("renditions"),
                                  pk=video_id)
        if video.status != VideoStatus.READY:
            return None, Response({"detail": "Video indisponible."},
                                  status=status.HTTP_404_NOT_FOUND)
        return video, None

    @staticmethod
    def manifest_response(text: str) -> HttpResponse:
        response = HttpResponse(text, content_type="application/vnd.apple.mpegurl")
        # The embedded presigned URLs expire; caching the manifest past that would
        # hand the player dead links.
        response["Cache-Control"] = "private, max-age=60"
        return response


@extend_schema(exclude=True)
class HlsMasterView(_SignedManifestView):
    def get(self, request, video_id):
        video, error = self.resolve(request, video_id)
        if error:
            return error
        text = playback_service.signed_master_playlist(
            video, request.query_params["token"], request
        )
        return self.manifest_response(text)


@extend_schema(exclude=True)
class HlsVariantView(_SignedManifestView):
    def get(self, request, video_id, label):
        video, error = self.resolve(request, video_id)
        if error:
            return error
        try:
            text = playback_service.signed_variant_playlist(video, label)
        except playback_service.PlaybackDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return self.manifest_response(text)


# --------------------------------------------------------------------------
# Studio (the uploader's own videos)
# --------------------------------------------------------------------------
@extend_schema(tags=["studio"])
class StudioVideoViewSet(viewsets.ModelViewSet):
    """CRUD over *your own* uploads. Creation happens through the tus endpoint,
    so POST is not exposed here."""

    permission_classes = [IsAuthenticated, IsOwner]
    owner_field = "uploader"
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]

    def get_queryset(self):
        # Schema generation instantiates the view with an AnonymousUser; without
        # this guard drf-spectacular cannot introspect the model and downgrades
        # the path parameter to an untyped string.
        if getattr(self, "swagger_fake_view", False):
            return Video.objects.none()
        # Scoped at the database level — the object permission is a second line
        # of defence, not the only one.
        return (
            Video.objects.filter(uploader=self.request.user)
            .with_related()
            .prefetch_related("renditions")
            .order_by("-uploaded_at")
        )

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return VideoUpdateSerializer
        return StudioVideoSerializer

    def perform_update(self, serializer):
        video = serializer.save()

        # Title/description/tags feed the search vector; refresh it inline so a
        # rename is searchable immediately rather than at the next beat tick.
        update_search_vector(video)

        audit.record(
            AuditAction.VIDEO_UPDATED,
            actor=self.request.user, target=video,
            metadata={"fields": list(serializer.validated_data.keys())},
            request=self.request,
        )

        if getattr(video, "_visibility_changed", False):
            audit.record(
                AuditAction.VIDEO_VISIBILITY_CHANGED,
                actor=self.request.user, target=video,
                metadata={"from": video._previous_visibility, "to": video.visibility},
                request=self.request,
            )
            # Crossing the private <-> public line means the HLS objects have to
            # move buckets, or the access model would be a lie.
            if video.hls_master_path:
                relocate_assets.delay(str(video.pk))

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        instance = self.get_object()
        return Response(StudioVideoSerializer(instance,
                                              context=self.get_serializer_context()).data)

    def perform_destroy(self, instance):
        video_id = str(instance.pk)
        prefix = instance.asset_prefix
        audit.record(
            AuditAction.VIDEO_DELETED, actor=self.request.user, target=instance,
            metadata={"title": instance.title}, request=self.request,
        )
        instance.delete()
        # Object cleanup is a background job: deleting hundreds of segments must
        # not hold the request open.
        delete_video_assets.delay(video_id, prefix)

    @extend_schema(request=None, responses={202: StudioVideoSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Re-run the pipeline for a failed video."""
        video = self.get_object()
        if video.status != VideoStatus.FAILED:
            raise ValidationError(
                {"detail": "Seules les videos en echec peuvent etre relancees."}
            )
        if video.transcode_attempts >= 5:
            raise ValidationError(
                {"detail": "Nombre maximal de tentatives atteint. "
                           "Televersez a nouveau le fichier."}
            )

        audit.record(AuditAction.VIDEO_TRANSCODE_RETRIED, actor=request.user,
                     target=video, request=request)
        start_transcoding_pipeline.delay(str(video.pk))

        video.refresh_from_db()
        return Response(
            StudioVideoSerializer(video, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None):
        """Polling fallback for the WebSocket progress channel.

        Present so a client behind a proxy that strips WebSocket upgrades still
        sees progress, rather than a frozen bar.
        """
        video = self.get_object()
        return Response(
            {
                "video_id": str(video.pk),
                "status": video.status,
                "stage": video.processing_stage,
                "stage_label": video.get_processing_stage_display(),
                "percent": video.processing_progress,
                "detail": video.failure_reason,
                "terminal": video.status in (VideoStatus.READY, VideoStatus.FAILED),
            }
        )


@extend_schema(tags=["studio"])
class StudioStatsView(APIView):
    """Creator-dashboard aggregates.

    Engagement counters are real columns but stay at zero until Phase 3 wires up
    views/likes/comments — the dashboard says so rather than inventing numbers.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = StudioStatsSerializer

    @extend_schema(responses={200: StudioStatsSerializer})
    def get(self, request):
        videos = Video.objects.filter(uploader=request.user)

        totals = videos.aggregate(
            total=Count("id"),
            views=Sum("view_count"),
            likes=Sum("like_count"),
            comments=Sum("comment_count"),
            duration=Sum("duration_seconds"),
        )
        by_status = {
            row["status"]: row["count"]
            for row in videos.values("status").annotate(count=Count("id"))
        }

        since = timezone.now() - timedelta(days=30)
        uploads_by_day = (
            videos.filter(uploaded_at__gte=since)
            .annotate(day=TruncDate("uploaded_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        top = (
            videos.filter(status=VideoStatus.READY)
            .order_by("-view_count")[:5]
            .values("id", "title", "view_count", "like_count", "comment_count")
        )

        # Real engagement over time, from the View rows themselves rather than
        # from the denormalised counter (which carries no timestamps).
        from apps.engagement.models import View as ViewModel

        views_by_day = (
            ViewModel.objects.filter(video__uploader=request.user, counted=True,
                                     created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        return Response(
            {
                "views_by_day": [
                    {"date": row["day"].isoformat(), "count": row["count"]}
                    for row in views_by_day
                ],
                "totals": {
                    "videos": totals["total"] or 0,
                    "views": totals["views"] or 0,
                    "likes": totals["likes"] or 0,
                    "comments": totals["comments"] or 0,
                    "duration_seconds": totals["duration"] or 0,
                },
                "by_status": {
                    "processing": by_status.get(VideoStatus.PROCESSING, 0),
                    "ready": by_status.get(VideoStatus.READY, 0),
                    "failed": by_status.get(VideoStatus.FAILED, 0),
                    "taken_down": by_status.get(VideoStatus.TAKEN_DOWN, 0),
                },
                "by_visibility": {
                    "public": videos.filter(visibility=Visibility.PUBLIC).count(),
                    "unlisted": videos.filter(visibility=Visibility.UNLISTED).count(),
                    "private": videos.filter(visibility=Visibility.PRIVATE).count(),
                },
                "uploads_by_day": [
                    {"date": row["day"].isoformat(), "count": row["count"]}
                    for row in uploads_by_day
                ],
                "top_videos": [
                    {**row, "id": str(row["id"])} for row in top
                ],
                # Views, likes and comments are live from Phase 3 onward.
                "engagement_available": True,
            }
        )
