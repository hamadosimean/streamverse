"""Django admin for the library.

Read-only throughout. These rows are *personal data* — what someone watched,
saved and who they follow — and there is no operational reason for staff to edit
them. Support can look one up; nobody can rewrite someone's history.
"""
from django.contrib import admin

from apps.library.models import Bookmark, Follow, WatchHistoryEntry


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WatchHistoryEntry)
class WatchHistoryEntryAdmin(_ReadOnlyAdmin):
    list_display = ("user", "video", "progress_display", "completed", "watch_count",
                    "last_watched_at")
    list_filter = ("completed", "last_watched_at")
    search_fields = ("user__username", "user__email", "video__title")
    date_hierarchy = "last_watched_at"
    list_select_related = ("user", "video")
    readonly_fields = [f.name for f in WatchHistoryEntry._meta.fields]

    @admin.display(description="Progression", ordering="progress_seconds")
    def progress_display(self, obj):
        return f"{obj.progress_seconds}s ({obj.progress_percent}%)"


@admin.register(Bookmark)
class BookmarkAdmin(_ReadOnlyAdmin):
    list_display = ("user", "video", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "user__email", "video__title")
    date_hierarchy = "created_at"
    list_select_related = ("user", "video")
    readonly_fields = [f.name for f in Bookmark._meta.fields]


@admin.register(Follow)
class FollowAdmin(_ReadOnlyAdmin):
    list_display = ("follower", "channel", "created_at")
    list_filter = ("created_at",)
    search_fields = ("follower__username", "channel__username")
    date_hierarchy = "created_at"
    list_select_related = ("follower", "channel")
    readonly_fields = [f.name for f in Follow._meta.fields]
