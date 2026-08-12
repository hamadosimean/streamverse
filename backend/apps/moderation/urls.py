from django.urls import path

from apps.moderation.views import (
    AdminDashboardView,
    ModerationLogView,
    ModerationStatsView,
    ReportDetailView,
    ReportQueueView,
    SanctionView,
    UserModerationDetailView,
    VideoModerationView,
)

app_name = "moderation"

urlpatterns = [
    path("moderation/reports/", ReportQueueView.as_view(), name="report-queue"),
    path("moderation/reports/<int:report_id>/", ReportDetailView.as_view(),
         name="report-detail"),
    path("moderation/videos/<uuid:video_id>/", VideoModerationView.as_view(),
         name="video-moderation"),
    path("moderation/sanctions/", SanctionView.as_view(), name="sanction"),
    path("moderation/users/<str:username>/", UserModerationDetailView.as_view(),
         name="user-detail"),
    path("moderation/log/", ModerationLogView.as_view(), name="log"),
    path("moderation/stats/", ModerationStatsView.as_view(), name="stats"),
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
]
