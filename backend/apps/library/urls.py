from django.urls import path

from apps.library.views import (
    BookmarkListView,
    BookmarkToggleView,
    FollowersListView,
    FollowingFeedView,
    FollowingListView,
    FollowToggleView,
    LibrarySummaryView,
    LikedVideosView,
    WatchHistoryEntryView,
    WatchHistoryView,
)

app_name = "library"

urlpatterns = [
    path("library/", LibrarySummaryView.as_view(), name="summary"),

    # Recently viewed
    path("library/history/", WatchHistoryView.as_view(), name="history"),
    path("library/history/<uuid:video_id>/", WatchHistoryEntryView.as_view(),
         name="history-entry"),

    # Bookmarks
    path("library/bookmarks/", BookmarkListView.as_view(), name="bookmarks"),
    path("videos/<uuid:video_id>/bookmark/", BookmarkToggleView.as_view(),
         name="bookmark-toggle"),

    # Likes
    path("library/likes/", LikedVideosView.as_view(), name="liked"),

    # Following
    path("library/following/", FollowingListView.as_view(), name="following"),
    path("library/feed/", FollowingFeedView.as_view(), name="following-feed"),
    path("accounts/channels/<str:username>/follow/", FollowToggleView.as_view(),
         name="follow-toggle"),
    path("accounts/channels/<str:username>/followers/", FollowersListView.as_view(),
         name="followers"),
]
