from django.contrib import admin
from django.utils.html import format_html

from apps.live.models import LiveChannel, LiveChatMessage, LiveRecording


class LiveRecordingInline(admin.TabularInline):
    model = LiveRecording
    extra = 0
    can_delete = False
    fields = ("started_at", "ended_at", "peak_viewer_count", "chat_message_count",
              "converted_video", "conversion_error")
    readonly_fields = fields
    max_num = 10
    ordering = ("-started_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LiveChannel)
class LiveChannelAdmin(admin.ModelAdmin):
    list_display = ("slug", "user", "status_badge", "current_viewer_count",
                    "all_time_peak_viewers", "total_sessions", "is_enabled",
                    "started_at")
    list_filter = ("status", "is_enabled", "chat_enabled", "record_sessions")
    search_fields = ("slug", "title", "user__username", "user__email")
    autocomplete_fields = ("user", "category")
    inlines = [LiveRecordingInline]
    list_select_related = ("user",)

    # The stream key is a publishing credential. It is never rendered in the
    # admin — not even read-only — because an admin page is one shoulder-surf
    # away from a channel takeover, and the owner can always rotate it from the
    # studio.
    exclude = ("stream_key",)
    readonly_fields = ("slug", "status", "started_at", "ended_at",
                       "current_viewer_count", "peak_viewer_count",
                       "all_time_peak_viewers", "total_sessions",
                       "stream_key_rotated_at", "created_at", "updated_at")

    fieldsets = (
        ("Chaine", {"fields": ("user", "slug", "title", "description", "category")}),
        ("Etat", {"fields": ("status", "started_at", "ended_at",
                             "current_viewer_count", "peak_viewer_count",
                             "all_time_peak_viewers", "total_sessions")}),
        ("Politique", {
            "fields": ("is_enabled", "chat_enabled", "record_sessions"),
            "description": "Decocher « is_enabled » bloque toute nouvelle "
                           "diffusion sans supprimer la chaine.",
        }),
        ("Securite", {
            "fields": ("stream_key_rotated_at",),
            "description": "La cle de flux n'est jamais affichee ici. "
                           "Le proprietaire peut la regenerer depuis son studio.",
        }),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {"live": "#ef4444", "offline": "#6b7280", "ended": "#f59e0b"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"), obj.get_status_display(),
        )


@admin.register(LiveRecording)
class LiveRecordingAdmin(admin.ModelAdmin):
    list_display = ("live_channel", "started_at", "ended_at", "peak_viewer_count",
                    "converted_video", "has_error")
    list_filter = ("started_at",)
    search_fields = ("live_channel__slug", "live_channel__user__username")
    date_hierarchy = "started_at"
    list_select_related = ("live_channel", "converted_video")
    readonly_fields = [f.name for f in LiveRecording._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Erreur", boolean=True)
    def has_error(self, obj):
        return bool(obj.conversion_error)


@admin.register(LiveChatMessage)
class LiveChatMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "live_channel", "user", "short_content",
                    "is_deleted")
    list_filter = ("is_deleted", "created_at")
    search_fields = ("content", "user__username", "live_channel__slug")
    date_hierarchy = "created_at"
    list_select_related = ("live_channel", "user")
    readonly_fields = ("live_channel", "session", "user", "content", "created_at")

    @admin.display(description="Message")
    def short_content(self, obj):
        return obj.content[:60] + ("..." if len(obj.content) > 60 else "")

    def has_add_permission(self, request):
        return False
