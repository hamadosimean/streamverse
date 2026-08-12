from django.contrib import admin
from django.utils.html import format_html

from apps.engagement.models import Comment, Like, Report, View


@admin.register(View)
class ViewAdmin(admin.ModelAdmin):
    """Read-only: view rows are evidence, not something to hand-edit."""

    list_display = ("video", "viewer", "watched_seconds", "counted", "created_at")
    list_filter = ("counted", "created_at")
    search_fields = ("video__title", "viewer__username", "viewer__email")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in View._meta.fields]
    list_select_related = ("video", "viewer")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ("video", "user", "reaction", "created_at")
    list_filter = ("is_like", "created_at")
    search_fields = ("video__title", "user__username", "user__email")
    list_select_related = ("video", "user")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Reaction", ordering="is_like")
    def reaction(self, obj):
        return "J'aime" if obj.is_like else "Je n'aime pas"


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("short_content", "author", "video", "is_reply_display",
                    "is_deleted", "created_at")
    list_filter = ("is_deleted", "created_at")
    search_fields = ("content", "author__username", "video__title")
    date_hierarchy = "created_at"
    list_select_related = ("author", "video", "parent_comment")
    readonly_fields = ("video", "author", "parent_comment", "reply_count",
                       "deleted_by", "created_at", "updated_at")
    actions = ["soft_delete_selected"]

    @admin.display(description="Commentaire")
    def short_content(self, obj):
        text = obj.content if not obj.is_deleted else "(supprime)"
        return text[:70] + ("..." if len(text) > 70 else "")

    @admin.display(description="Reponse", boolean=True)
    def is_reply_display(self, obj):
        return obj.parent_comment_id is not None

    @admin.action(description="Supprimer (soft delete) les commentaires selectionnes")
    def soft_delete_selected(self, request, queryset):
        from apps.engagement.services import delete_comment

        count = 0
        for comment in queryset.filter(is_deleted=False):
            delete_comment(comment, actor=request.user,
                           reason="Suppression depuis l'administration.")
            count += 1
        self.message_user(request, f"{count} commentaire(s) supprime(s).")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Visible here for reference; the working moderation queue is a dedicated
    React view (Phase 6), because triage is a decision workflow, not CRUD."""

    list_display = ("created_at", "reason", "status_badge", "target_type",
                    "reporter", "reviewed_by")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("details", "reporter__username", "object_id",
                     "resolution_note")
    date_hierarchy = "created_at"
    list_select_related = ("reporter", "reviewed_by", "content_type")
    readonly_fields = ("reporter", "content_type", "object_id", "reason",
                       "details", "created_at", "updated_at")

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {"pending": "#f59e0b", "actioned": "#10b981", "dismissed": "#6b7280"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"), obj.get_status_display(),
        )

    @admin.display(description="Type de cible")
    def target_type(self, obj):
        return obj.content_type.model
