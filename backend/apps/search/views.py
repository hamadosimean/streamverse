"""Search and discovery endpoints."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Tag
from apps.search.services import related_videos, search_videos
from apps.videos.models import Video
from apps.videos.serializers import VideoCardSerializer


@extend_schema(tags=["search"])
class VideoSearchView(ListAPIView):
    """Full-text search across title, tags and description.

    The response carries a `mode` field (`fulltext` / `fuzzy` / `none`) so the
    UI can tell the user when it fell back to approximate matching instead of
    silently presenting near-misses as exact hits.
    """

    permission_classes = [AllowAny]
    serializer_class = VideoCardSerializer

    @extend_schema(parameters=[
        OpenApiParameter("q", str, description="Requete. Supporte \"phrase exacte\" "
                                              "et -exclusion (syntaxe websearch)."),
        OpenApiParameter("category", str, description="Filtrer par slug de categorie."),
    ])
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        response.data["mode"] = getattr(self, "_mode", "none")
        response.data["query"] = request.query_params.get("q", "")
        return response

    def get_queryset(self):
        query = self.request.query_params.get("q", "")
        category = self.request.query_params.get("category")

        base = Video.objects.publicly_listed().with_related()
        if category:
            base = base.filter(category__slug__iexact=category)

        results, mode = search_videos(query, queryset=base)
        self._mode = mode
        return results


@extend_schema(tags=["search"])
class RelatedVideosView(APIView):
    """Content-based related videos for one video.

    Ranked by shared tags, then shared category. Explicitly **not** personalised
    and **not** machine-learned — see the README scope notes.
    """

    permission_classes = [AllowAny]

    @extend_schema(responses={200: VideoCardSerializer(many=True)})
    def get(self, request, video_id):
        user = request.user if request.user.is_authenticated else None
        video = get_object_or_404(
            Video.objects.visible_to(user).prefetch_related("tags"), pk=video_id
        )

        results = related_videos(video, limit=12)
        return Response(
            {
                "results": VideoCardSerializer(
                    results, many=True, context={"request": request}
                ).data,
                # Surfaced so the UI can label the rail honestly.
                "strategy": "content_based",
            }
        )


@extend_schema(tags=["search"])
class SearchSuggestionsView(APIView):
    """Lightweight autocomplete: matching tags plus a few video titles."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("q", str)],
        responses={200: dict},
    )
    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response({"tags": [], "videos": []})

        tags = list(
            Tag.objects.filter(name__istartswith=query.lower())
            .order_by("-usage_count")
            .values("name", "slug")[:6]
        )

        videos = list(
            Video.objects.publicly_listed()
            .filter(title__icontains=query)
            .order_by("-view_count")
            .values("id", "title")[:6]
        )
        for item in videos:
            item["id"] = str(item["id"])

        return Response({"tags": tags, "videos": videos})
