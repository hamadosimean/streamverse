"""Django admin for moderation.

Read-only. The working queue is a dedicated React view at /manage/moderation,
because triaging a report is a decision workflow — you need the content, the
reporter, the author's history and four possible actions on one screen, not a
model form. What is here is the immutable record of what was decided.
"""
from django.contrib import admin
from django.utils.html import format_html

from apps.moderation.models import ModerationAction, UserSanction


@admin.register(ModerationAction)
class ModerationActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "moderator", "action", "target_repr",
                    "affected_user", "short_reason")
    list_filter = ("action", "created_at")
    search_fields = ("target_repr", "reason", "moderator__username",
                     "affected_user__username")
    date_hierarchy = "created_at"
    list_select_related = ("moderator", "affected_user")
    readonly_fields = [f.name for f in ModerationAction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Motif")
    def short_reason(self, obj):
        return obj.reason[:70] + ("..." if len(obj.reason) > 70 else "")


@admin.register(UserSanction)
class UserSanctionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "type_badge", "moderator", "expires_at",
                    "lifted_at", "active")
    list_filter = ("type", "created_at")
    search_fields = ("user__username", "user__email", "reason")
    date_hierarchy = "created_at"
    list_select_related = ("user", "moderator")
    readonly_fields = [f.name for f in UserSanction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Type", ordering="type")
    def type_badge(self, obj):
        colors = {"warning": "#f59e0b", "suspension": "#ef4444", "ban": "#7f1d1d"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.type, "#6b7280"), obj.get_type_display(),
        )

    @admin.display(description="En vigueur", boolean=True)
    def active(self, obj):
        return obj.is_active
