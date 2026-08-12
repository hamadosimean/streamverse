import django_filters as filters

from apps.videos.models import Video


class VideoFilter(filters.FilterSet):
    """Public catalogue filtering.

    `q` is a plain trigram-free ILIKE for Phase 2; Phase 3 replaces it with the
    PostgreSQL `tsvector` + GIN full-text search the spec asks for.
    """

    category = filters.CharFilter(field_name="category__slug", lookup_expr="iexact")
    tag = filters.CharFilter(field_name="tags__slug", lookup_expr="iexact")
    uploader = filters.CharFilter(field_name="uploader__username", lookup_expr="iexact")
    q = filters.CharFilter(method="filter_search")
    min_duration = filters.NumberFilter(field_name="duration_seconds", lookup_expr="gte")
    max_duration = filters.NumberFilter(field_name="duration_seconds", lookup_expr="lte")

    class Meta:
        model = Video
        fields = ("category", "tag", "uploader", "q")

    def filter_search(self, queryset, name, value):
        value = (value or "").strip()
        if not value:
            return queryset
        return queryset.filter(title__icontains=value).distinct()
