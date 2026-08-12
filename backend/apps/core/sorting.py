"""Shared, whitelisted sorting for list endpoints.

Why a whitelist rather than passing `?ordering=` through to `order_by()`:

* an arbitrary field name lets a caller order by columns that are not in the
  serializer — `failure_reason`, `original_filename`, a user's `email` — and
  ordering leaks content even when the field is never rendered. Sorting a list
  by a hidden column and reading the resulting order is a real inference channel;
* `order_by()` on an unindexed column is an easy accidental table scan;
* a typo in a client would silently reorder by nothing at all.

So each view declares a small map of public sort keys to concrete orderings, and
anything else falls back to the default.

**Unknown keys fall back rather than 400.** A bookmarked URL carrying a sort key
that has since been renamed should still show results, not an error page. The
response echoes the key that was actually applied, so a client can tell the
difference between "you got what you asked for" and "you got the default".
"""
from __future__ import annotations

from rest_framework.response import Response


class SortOption:
    """One public sort key.

    `ordering` is a tuple passed straight to `order_by`. A secondary key is
    almost always worth including: ordering by a non-unique column alone gives
    the database licence to return ties in any order, which makes pagination
    unstable — the same row can appear on two pages, or on neither.
    """

    __slots__ = ("key", "ordering", "label")

    def __init__(self, key: str, ordering: tuple[str, ...], label: str = ""):
        self.key = key
        self.ordering = ordering
        self.label = label or key


class SortableMixin:
    """Adds `?sort=` to a ListAPIView.

    Declare on the view:

        sort_options = {
            "recent": SortOption("recent", ("-published_at", "-id")),
            ...
        }
        default_sort = "recent"
    """

    sort_options: dict[str, SortOption] = {}
    default_sort: str = ""
    sort_query_param: str = "sort"

    def get_sort_option(self) -> SortOption | None:
        if not self.sort_options:
            return None

        requested = self.request.query_params.get(self.sort_query_param)
        if requested in self.sort_options:
            self.applied_sort = requested
            return self.sort_options[requested]

        fallback = self.default_sort or next(iter(self.sort_options))
        self.applied_sort = fallback
        return self.sort_options.get(fallback)

    def apply_sort(self, queryset):
        option = self.get_sort_option()
        if option is None:
            return queryset
        return queryset.order_by(*option.ordering)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Echo what was actually applied so the UI can reflect a fallback rather
        # than showing a selected option that the server ignored.
        if isinstance(response, Response) and isinstance(response.data, dict):
            response.data["sort"] = getattr(self, "applied_sort", self.default_sort)
            response.data["sort_options"] = list(self.sort_options)
        return response
