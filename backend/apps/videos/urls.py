from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.videos.tus import (
    TusCollectionView,
    TusUploadView,
    UploadSessionResultView,
)
from apps.videos.views import (
    HlsMasterView,
    HlsVariantView,
    HomeFeedView,
    PlaybackView,
    StudioStatsView,
    StudioVideoViewSet,
    VideoDetailView,
    VideoListView,
)

app_name = "videos"

router = DefaultRouter()
router.register("studio/videos", StudioVideoViewSet, basename="studio-video")

urlpatterns = [
    # Resumable upload (tus 1.0.0)
    path("uploads/", TusCollectionView.as_view(), name="tus-collection"),
    path("uploads/<uuid:upload_id>/", TusUploadView.as_view(), name="tus-upload"),
    path("uploads/<uuid:upload_id>/video/", UploadSessionResultView.as_view(),
         name="upload-result"),

    # Public catalogue
    path("feed/", HomeFeedView.as_view(), name="home-feed"),
    path("videos/", VideoListView.as_view(), name="video-list"),
    path("videos/<uuid:pk>/", VideoDetailView.as_view(), name="video-detail"),

    # Playback
    path("videos/<uuid:pk>/playback/", PlaybackView.as_view(), name="playback"),
    # Django-served manifests — private videos only. Text, never media bytes.
    path("videos/<uuid:video_id>/hls/master.m3u8", HlsMasterView.as_view(),
         name="hls-master"),
    path("videos/<uuid:video_id>/hls/<str:label>.m3u8", HlsVariantView.as_view(),
         name="hls-variant"),

    # Studio
    path("studio/stats/", StudioStatsView.as_view(), name="studio-stats"),
]

urlpatterns += router.urls
