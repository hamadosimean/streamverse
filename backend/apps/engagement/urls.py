from django.urls import path

from apps.engagement.views import (
    CommentDetailView,
    MyReportsView,
    ReportCreateView,
    ReportReasonsView,
    VideoCommentListCreateView,
    VideoReactionView,
    VideoViewPingView,
)

app_name = "engagement"

urlpatterns = [
    # Per-video engagement
    path("videos/<uuid:video_id>/view/", VideoViewPingView.as_view(), name="view-ping"),
    path("videos/<uuid:video_id>/reaction/", VideoReactionView.as_view(),
         name="reaction"),
    path("videos/<uuid:video_id>/comments/", VideoCommentListCreateView.as_view(),
         name="comment-list"),

    # Single comment
    path("comments/<int:comment_id>/", CommentDetailView.as_view(), name="comment-detail"),

    # Reports
    path("reports/", ReportCreateView.as_view(), name="report-create"),
    path("reports/mine/", MyReportsView.as_view(), name="report-mine"),
    path("reports/reasons/", ReportReasonsView.as_view(), name="report-reasons"),
]
