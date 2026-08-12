from django.urls import path

from apps.search.views import (
    RelatedVideosView,
    SearchSuggestionsView,
    VideoSearchView,
)

app_name = "search"

urlpatterns = [
    path("search/", VideoSearchView.as_view(), name="video-search"),
    path("search/suggest/", SearchSuggestionsView.as_view(), name="search-suggest"),
    path("videos/<uuid:video_id>/related/", RelatedVideosView.as_view(),
         name="related-videos"),
]
