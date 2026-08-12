"""Library API: history, bookmarks, liked videos, follows and the following feed.

Every endpoint here is scoped to `request.user` at the queryset level. There is
no path by which one user can read another's library — a viewer's watch history
in particular is among the most sensitive data this platform holds.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.engagement.models import Like
from apps.library import services
from apps.library.models import Bookmark, Follow, WatchHistoryEntry
from apps.library.serializers import (
    BookmarkSerializer,
    BookmarkStateSerializer,
    FollowedChannelSerializer,
    FollowStateSerializer,
    LibraryVideoSerializer,
    WatchHistoryEntrySerializer,
)
from apps.videos.models import Video

logger = logging.getLogger(__name__)
User = get_user_model()


class _ViewerStateMixin:
    """Adds the caller's bookmark/reaction state to a page in two queries."""

    def get_serializer_context(self):
        context = super().get_serializer_context()
        page = getattr(self, "_page_videos", None)
        if page is not None:
            bookmarked, reactions = services.annotate_viewer_state(
                page, self.request.user
            )
            context["bookmarked"] = bookmarked
            context["reactions"] = reactions
        return context

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        # Works whether the page holds Videos or rows that wrap one.
        self._page_videos = [
            row if isinstance(row, Video) else getattr(row, "video", None)
            for row in rows
        ]
        self._page_videos = [v for v in self._page_videos if v is not None]
        return page


# --------------------------------------------------------------------------
# Watch history
# --------------------------------------------------------------------------
@extend_schema(tags=["library"])
class WatchHistoryView(_ViewerStateMixin, ListAPIView):
    """Recently viewed, most recent first."""

    permission_classes = [IsAuthenticated]
    serializer_class = WatchHistoryEntrySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WatchHistoryEntry.objects.none()
        queryset = (
            WatchHistoryEntry.objects.filter(user=self.request.user)
            .select_related("video", "video__uploader", "video__category")
            .prefetch_related("video__tags")
            # A video removed by moderation should leave someone's history
            # rather than sit there as a dead card.
            .exclude(video__status="taken_down")
        )
        if self.request.query_params.get("resumable") == "true":
            # Filtered in Python: `is_resumable` is a computed property, and a
            # SQL equivalent would duplicate the rule in two places.
            return [entry for entry in queryset if entry.is_resumable]
        return queryset.order_by("-last_watched_at")

    @extend_schema(operation_id="library_history_clear", responses={204: None})
    def delete(self, request):
        """Clear the whole history.

        Deletes only `WatchHistoryEntry`. The analytics `View` rows are left
        alone on purpose — clearing your history must not silently decrement
        someone else's view count.
        """
        deleted, _ = WatchHistoryEntry.objects.filter(user=request.user).delete()
        logger.info("history cleared for %s (%d entries)", request.user.pk, deleted)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["library"])
class WatchHistoryEntryView(APIView):
    """Remove a single video from history."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="library_history_remove_video", responses={204: None})
    def delete(self, request, video_id):
        WatchHistoryEntry.objects.filter(user=request.user, video_id=video_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Bookmarks
# --------------------------------------------------------------------------
@extend_schema(tags=["library"])
class BookmarkListView(_ViewerStateMixin, ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookmarkSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Bookmark.objects.none()
        return (
            Bookmark.objects.filter(user=self.request.user)
            .select_related("video", "video__uploader", "video__category")
            .prefetch_related("video__tags")
            .exclude(video__status="taken_down")
            .order_by("-created_at")
        )


@extend_schema(tags=["library"])
class BookmarkToggleView(APIView):
    """Save or unsave a video. Idempotent per call — it toggles."""

    permission_classes = [IsAuthenticated]
    serializer_class = BookmarkStateSerializer

    @extend_schema(responses={200: BookmarkStateSerializer})
    def get(self, request, video_id):
        return Response({
            "is_bookmarked": Bookmark.objects.filter(
                user=request.user, video_id=video_id).exists()
        })

    @extend_schema(request=None, responses={200: BookmarkStateSerializer})
    def post(self, request, video_id):
        video = get_object_or_404(Video.objects.visible_to(request.user), pk=video_id)
        note = request.data.get("note", "") if isinstance(request.data, dict) else ""
        is_bookmarked, _ = services.toggle_bookmark(user=request.user, video=video,
                                                    note=note)
        return Response({"is_bookmarked": is_bookmarked})


# --------------------------------------------------------------------------
# Liked videos
# --------------------------------------------------------------------------
@extend_schema(tags=["library"])
class LikedVideosView(_ViewerStateMixin, ListAPIView):
    """Videos the caller liked. Dislikes are deliberately not listed —
    nobody wants a browsable shelf of things they disliked."""

    permission_classes = [IsAuthenticated]
    serializer_class = LibraryVideoSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Video.objects.none()
        liked = Like.objects.filter(user=self.request.user, is_like=True)
        # Ordered by *when the caller liked it* via a correlated subquery. A
        # join on `likes` would order correctly but multiply each video by its
        # like count, so the page would repeat rows.
        liked_at = liked.filter(video=OuterRef("pk")).values("created_at")[:1]
        return (
            Video.objects.filter(pk__in=liked.values("video_id"))
            .exclude(status="taken_down")
            .with_related()
            .annotate(liked_at=Subquery(liked_at))
            .order_by("-liked_at")
        )


# --------------------------------------------------------------------------
# Following
# --------------------------------------------------------------------------
@extend_schema(tags=["library"])
class FollowToggleView(APIView):
    """Follow or unfollow a channel."""

    permission_classes = [IsAuthenticated]
    serializer_class = FollowStateSerializer

    @extend_schema(responses={200: FollowStateSerializer})
    def get(self, request, username):
        channel = get_object_or_404(User, username=username)
        return Response({
            "is_following": Follow.objects.filter(
                follower=request.user, channel=channel).exists(),
            "follower_count": channel.follower_count,
        })

    @extend_schema(request=None, responses={200: FollowStateSerializer})
    def post(self, request, username):
        channel = get_object_or_404(
            User.objects.filter(is_active=True, is_suspended=False), username=username
        )
        try:
            is_following, count = services.toggle_follow(follower=request.user,
                                                         channel=channel)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response({"is_following": is_following, "follower_count": count})


@extend_schema(tags=["library"])
class FollowingListView(ListAPIView):
    """Channels the caller follows, with how much each has published."""

    permission_classes = [IsAuthenticated]
    serializer_class = FollowedChannelSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Follow.objects.none()
        published = Q(channel__videos__status="ready",
                      channel__videos__visibility="public")
        return (
            Follow.objects.filter(follower=self.request.user)
            .select_related("channel")
            .annotate(
                video_count=Count("channel__videos", filter=published, distinct=True),
                latest_video_at=Max("channel__videos__published_at", filter=published),
            )
            .order_by("-created_at")
        )


@extend_schema(tags=["library"])
class FollowersListView(ListAPIView):
    """A channel's followers. Public — the count is already public."""

    permission_classes = [AllowAny]
    serializer_class = FollowedChannelSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Follow.objects.none()
        channel = get_object_or_404(User, username=self.kwargs["username"])
        return Follow.objects.filter(channel=channel).select_related(
            "follower"
        ).order_by("-created_at")


@extend_schema(tags=["library"])
class FollowingFeedView(_ViewerStateMixin, ListAPIView):
    """Recent videos from the channels the caller follows.

    Chronological, not ranked. The platform has no recommendation model and this
    feed does not pretend to be one — it is "what the people you follow posted,
    newest first".
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LibraryVideoSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Video.objects.none()
        channel_ids = services.followed_channel_ids(self.request.user)
        if not channel_ids:
            return Video.objects.none()
        return (
            Video.objects.publicly_listed()
            .filter(uploader_id__in=channel_ids)
            .with_related()
            .order_by("-published_at")
        )


@extend_schema(tags=["library"])
class LibrarySummaryView(APIView):
    """Counts for the library nav, in one request instead of four."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        history = WatchHistoryEntry.objects.filter(user=request.user).exclude(
            video__status="taken_down"
        )
        return Response({
            "history": history.count(),
            "resumable": sum(1 for entry in history.select_related("video")[:200]
                             if entry.is_resumable),
            "bookmarks": Bookmark.objects.filter(user=request.user).exclude(
                video__status="taken_down").count(),
            "liked": Like.objects.filter(user=request.user, is_like=True).count(),
            "following": Follow.objects.filter(follower=request.user).count(),
            "followers": request.user.follower_count,
        })
