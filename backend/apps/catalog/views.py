from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from apps.catalog.models import Category, Tag
from apps.catalog.serializers import CategorySerializer, TagSerializer


@extend_schema(tags=["catalog"])
class CategoryListView(generics.ListAPIView):
    """Public category list, annotated with the count of publicly visible videos."""

    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Category.objects.filter(is_active=True)
            .annotate(
                video_count=Count(
                    "videos",
                    filter=Q(videos__status="ready", videos__visibility="public"),
                    distinct=True,
                )
            )
            .order_by("display_order", "name")
        )


@extend_schema(tags=["catalog"])
class TagListView(generics.ListAPIView):
    """Tag autocomplete / popular tags. `?q=` filters by prefix."""

    permission_classes = [AllowAny]
    serializer_class = TagSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Tag.objects.all()
        query = self.request.query_params.get("q")
        if query:
            qs = qs.filter(name__istartswith=query.strip().lower())
        return qs.order_by("-usage_count", "name")[:50]
