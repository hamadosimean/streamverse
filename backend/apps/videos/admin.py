"""Django admin for the video catalogue.

Read-heavy on purpose: pipeline-owned fields (status, paths, progress, source
characteristics) are read-only so an admin cannot hand-edit a video into a state
the transcoder never produced. Decision workflows — moderation queue, ad
campaigns — are dedicated React views, not admin CRUD.
"""
from django.contrib import admin
from django.utils.html import format_html

from apps.videos.models import (
    UploadSession,
    Video,
    VideoRendition,
    VideoThumbnail,
)


class VideoRenditionInline(admin.TabularInline):
    model = VideoRendition
    extra = 0
    can_delete = False
    readonly_fields = ("label", "width", "height", "video_bitrate_kbps",
                       "audio_bitrate_kbps", "hls_playlist_path", "file_size",
                       "segment_count", "codecs", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


class VideoThumbnailInline(admin.TabularInline):
    model = VideoThumbnail
    extra = 0
    can_delete = False
    readonly_fields = ("timestamp_offset", "image_path", "is_poster",
                       "sprite_x", "sprite_y")
    max_num = 10

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "uploader", "status_badge", "visibility", "category",
                    "duration_display", "rendition_count", "view_count", "uploaded_at")
    list_filter = ("status", "visibility", "category", "uploaded_at")
    search_fields = ("title", "description", "uploader__username", "uploader__email",
                     "id")
    autocomplete_fields = ("uploader", "category", "tags")
    date_hierarchy = "uploaded_at"
    inlines = [VideoRenditionInline, VideoThumbnailInline]
    list_select_related = ("uploader", "category")

    readonly_fields = (
        "id", "status", "processing_stage", "processing_progress", "failure_reason",
        "transcode_attempts", "duration_seconds", "source_width", "source_height",
        "source_resolution", "source_video_codec", "source_audio_codec", "has_audio",
        "original_key", "original_filename", "original_size_bytes",
        "original_mime_type", "storage_bucket", "hls_master_path", "poster_path",
        "sprite_path", "thumbnail_vtt_path", "sprite_meta", "view_count",
        "like_count", "dislike_count", "comment_count", "uploaded_at",
        "published_at", "created_at", "updated_at", "taken_down_at",
    )

    fieldsets = (
        ("Contenu", {"fields": ("id", "title", "description", "uploader",
                                "category", "tags", "visibility")}),
        ("Pipeline de transcodage", {
            "fields": ("status", "processing_stage", "processing_progress",
                       "failure_reason", "transcode_attempts"),
            "description": "Champs pilotes par Celery — lecture seule.",
        }),
        ("Source", {"fields": ("duration_seconds", "source_resolution",
                               "source_video_codec", "source_audio_codec",
                               "has_audio", "original_filename",
                               "original_size_bytes", "original_mime_type",
                               "original_key")}),
        ("Stockage objet", {"fields": ("storage_bucket", "hls_master_path",
                                       "poster_path", "sprite_path",
                                       "thumbnail_vtt_path", "sprite_meta")}),
        ("Engagement", {"fields": ("view_count", "like_count", "dislike_count",
                                   "comment_count")}),
        ("Moderation", {"fields": ("takedown_reason", "taken_down_at")}),
        ("Dates", {"fields": ("uploaded_at", "published_at", "created_at",
                              "updated_at")}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {"processing": "#f59e0b", "ready": "#10b981",
                  "failed": "#ef4444", "taken_down": "#6b7280"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"), obj.get_status_display(),
        )

    @admin.display(description="Duree", ordering="duration_seconds")
    def duration_display(self, obj):
        minutes, seconds = divmod(obj.duration_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    @admin.display(description="Rendus")
    def rendition_count(self, obj):
        return obj.renditions.count()


@admin.register(VideoRendition)
class VideoRenditionAdmin(admin.ModelAdmin):
    list_display = ("video", "label", "width", "height", "video_bitrate_kbps",
                    "segment_count", "file_size")
    list_filter = ("label",)
    search_fields = ("video__title", "video__id")
    readonly_fields = [f.name for f in VideoRendition._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "filename", "progress_display", "status",
                    "created_at", "expires_at")
    list_filter = ("status", "created_at")
    search_fields = ("filename", "user__username", "user__email", "id")
    readonly_fields = [f.name for f in UploadSession._meta.fields]

    @admin.display(description="Progression")
    def progress_display(self, obj):
        if not obj.upload_length:
            return "-"
        percent = min(100, int(obj.offset * 100 / obj.upload_length))
        return format_html(
            '<div style="background:#e5e7eb;border-radius:6px;width:120px;">'
            '<div style="background:#6366f1;width:{}%;height:12px;border-radius:6px;">'
            "</div></div> {}%",
            percent, percent,
        )

    def has_add_permission(self, request):
        return False
