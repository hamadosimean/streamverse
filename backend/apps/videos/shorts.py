"""The Shorts surface.

A Short is an ordinary `Video` — same upload, same transcoding chain, same
storage and playback. What differs is the *surface*: a full-screen vertical feed
instead of a grid, so the API's job here is to hand the client a batch of
playable shorts with everything the overlay needs, in one request.

Why one request rather than a card list plus a playback call per item: the feed
autoplays as you scroll, so the client needs the manifest URL for the next clip
*before* it comes into view. Making it fetch playback per swipe puts a network
round-trip in the middle of a gesture.
"""
from __future__ import annotations

import logging

from django.db.models import TextField, Value
from django.db.models.functions import Cast, Concat, MD5
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.sorting import SortableMixin, SortOption
from apps.videos.models import Video
from apps.videos.serializers import VideoCardSerializer, asset_url
from apps.videos.services import playback as playback_service

logger = logging.getLogger(__name__)


class ShortSerializer(VideoCardSerializer):
    """A Short, ready to play, with the overlay's data attached."""

    playback_url = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    is_following_uploader = serializers.SerializerMethodField()

    class Meta(VideoCardSerializer.Meta):
        fields = VideoCardSerializer.Meta.fields + (
            "description", "comment_count", "dislike_count", "is_short",
            "source_width", "source_height", "playback_url", "is_bookmarked",
            "my_reaction", "is_following_uploader",
        )
        read_only_fields = fields

    def get_playback_url(self, obj) -> str | None:
        """The HLS master, resolved the same way the watch page does.

        Shorts are public by definition (the feed only lists public videos), so
        this is always the direct object-storage URL — Django stays out of the
        media path here exactly as it does everywhere else.
        """
        if not obj.hls_master_path:
            return None
        return asset_url(obj, obj.hls_master_path)

    def get_is_bookmarked(self, obj) -> bool:
        return obj.pk in (self.context.get("bookmarked") or set())

    def get_my_reaction(self, obj) -> str | None:
        reactions = self.context.get("reactions") or {}
        if obj.pk not in reactions:
            return None
        return "like" if reactions[obj.pk] else "dislike"

    def get_is_following_uploader(self, obj) -> bool:
        return obj.uploader_id in (self.context.get("followed") or set())


class _ShortsContextMixin:
    """Resolve the viewer's per-item state for a whole page in three queries.

    A vertical feed shows one item at a time but loads a batch, so doing this
    per row would be three queries per swipe-ahead item for no benefit.
    """

    def _viewer_context(self, videos):
        context = {"request": self.request}
        user = self.request.user

        if not user.is_authenticated or not videos:
            return context

        from apps.library.models import Follow
        from apps.library.services import annotate_viewer_state

        bookmarked, reactions = annotate_viewer_state(videos, user)
        context["bookmarked"] = bookmarked
        context["reactions"] = reactions
        context["followed"] = set(
            Follow.objects.filter(
                follower=user, channel_id__in={v.uploader_id for v in videos}
            ).values_list("channel_id", flat=True)
        )
        return context


@extend_schema(tags=["shorts"])
class ShortsFeedView(_ShortsContextMixin, SortableMixin, ListAPIView):
    """The vertical feed.

    Shuffled by default, or ordered explicitly — **not** an engagement-optimised
    ranking. This platform has no recommendation model and a Shorts feed is
    exactly where one would normally hide; the API says which ordering it used
    and the UI repeats it.
    """

    permission_classes = [AllowAny]
    serializer_class = ShortSerializer

    # `shuffle` is handled in get_queryset — its ordering is computed per request
    # from the seed, so it cannot be a static tuple like the others. It is listed
    # here so it appears in `sort_options` and survives the whitelist check.
    sort_options = {
        "shuffle": SortOption("shuffle", ("?",)),
        "recent": SortOption("recent", ("-published_at", "-id")),
        "popular": SortOption("popular", ("-view_count", "-published_at")),
        "liked": SortOption("liked", ("-like_count", "-published_at")),
        "oldest": SortOption("oldest", ("published_at", "id")),
    }
    default_sort = "shuffle"

    @extend_schema(parameters=[
        OpenApiParameter("sort", str,
                         description="shuffle | recent | popular | liked | oldest"),
        OpenApiParameter("category", str),
        OpenApiParameter("seed", str,
                         description="Shuffle seed. The same seed reproduces the "
                                     "same order; omit it for a fresh shuffle."),
        OpenApiParameter("start", str,
                         description="Video id to place first — deep-linking into "
                                     "the feed at a specific Short."),
    ])
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Say which ordering was actually used. This used to be hardcoded to
        # "chronological", which was already untrue for ?sort=popular.
        response.data["ranking"] = self.RANKING_LABELS.get(
            getattr(self, "applied_sort", self.default_sort), "explicit"
        )
        return response

    RANKING_LABELS = {
        "shuffle": "random",
        "recent": "chronological",
        "oldest": "chronological",
        "popular": "view_count",
        "liked": "like_count",
    }

    def _shuffle(self, queryset):
        """Order pseudo-randomly, but reproducibly for a given seed.

        Plain `order_by("?")` would reshuffle on every request, so page 2 would
        be drawn from a different order than page 1 — the same Short can then
        appear twice or never. Hashing the row id together with a caller-supplied
        seed gives an order that is arbitrary but *stable*: the client keeps one
        seed for as long as it is scrolling a feed, and asks for a new one when
        the viewer wants a fresh shuffle.

        `id` is the tiebreaker so equal hashes (or none, if the seed is reused
        against a changed table) still paginate deterministically.

        Cost: the hash is not indexable, so this sorts every Short matching the
        filter. The `(is_short, status, visibility, -published_at)` index still
        narrows the set; only the ordering is a sort. Fine while Shorts number in
        the thousands — past that, precompute a shuffle bucket per row instead.
        """
        seed = (self.request.query_params.get("seed") or "")[:64]
        return queryset.annotate(
            _shuffle_key=MD5(
                Concat(Cast("id", TextField()), Value(seed), output_field=TextField())
            )
        ).order_by("_shuffle_key", "id")

    def get_queryset(self):
        queryset = Video.objects.shorts().with_related()

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug__iexact=category)

        # Resolve the sort key first so an unknown ?sort= still falls back to
        # the default (shuffle) rather than silently landing in apply_sort.
        option = self.get_sort_option()
        if option is not None and option.key == "shuffle":
            return self._shuffle(queryset)
        return self.apply_sort(queryset)

    def get_serializer_context(self):
        page = getattr(self, "_page_videos", [])
        return {**super().get_serializer_context(), **self._viewer_context(page)}

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self._page_videos = list(page if page is not None else queryset)
        return page

    def list(self, request, *args, **kwargs):
        """Optionally pin one Short to the front.

        Opening `/shorts/<id>` must start on that clip and still allow scrolling
        onward, so the requested item is hoisted to the top of the first page
        rather than served as a separate one-item endpoint.
        """
        response = super().list(request, *args, **kwargs)
        start = request.query_params.get("start")
        if not start or not isinstance(response.data, dict):
            return response

        results = response.data.get("results") or []
        index = next((i for i, item in enumerate(results)
                      if str(item.get("id")) == str(start)), None)

        if index is None:
            # Not on this page (or not a Short at all) — fetch it explicitly so
            # a deep link still opens on the right clip.
            video = Video.objects.shorts().with_related().filter(pk=start).first()
            if video is not None:
                data = self.get_serializer_class()(
                    video, context=self._viewer_context([video])
                ).data
                response.data["results"] = [data, *results]
        elif index > 0:
            results.insert(0, results.pop(index))

        return response


@extend_schema(tags=["shorts"])
class ShortDetailView(_ShortsContextMixin, APIView):
    """One Short, for a deep link or a share target."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: ShortSerializer})
    def get(self, request, video_id):
        user = request.user if request.user.is_authenticated else None
        video = get_object_or_404(
            Video.objects.visible_to(user).with_related(), pk=video_id
        )
        return Response(
            ShortSerializer(video, context=self._viewer_context([video])).data
        )
