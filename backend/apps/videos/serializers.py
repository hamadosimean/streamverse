"""Video serializers.

Three read shapes, deliberately distinct:

* ``VideoCardSerializer``   — what a grid needs. No description, no renditions.
* ``VideoDetailSerializer`` — the watch page.
* ``StudioVideoSerializer`` — the uploader's own view, and the only one that ever
  exposes pipeline internals (stage, progress, failure reason, source file info).

Keeping them separate is what stops a public list endpoint from leaking a
private video's failure reason or original filename.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.accounts.serializers import PublicChannelSerializer
from apps.catalog.models import Category, Tag
from apps.catalog.serializers import CategorySerializer, TagSerializer
from apps.core import storage
from apps.videos.models import Video, VideoRendition, VideoStatus, Visibility


def asset_url(video: Video, path: str) -> str | None:
    """Resolve a stored object key to something the browser can fetch.

    Public/unlisted assets get a plain public URL; private ones get a short-lived
    presigned URL. This is the same split as playback, applied to posters.
    """
    if not path:
        return None
    if video.is_public_asset:
        return storage.public_url(path)
    return storage.presigned_url(
        path, bucket=video.storage_bucket or settings.MINIO_PRIVATE_BUCKET
    )


class VideoRenditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoRendition
        fields = ("label", "width", "height", "video_bitrate_kbps", "file_size",
                  "segment_count")
        read_only_fields = fields


class VideoCardSerializer(serializers.ModelSerializer):
    uploader = PublicChannelSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    poster_url = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = ("id", "title", "uploader", "category", "duration_seconds",
                  "poster_url", "view_count", "like_count", "published_at",
                  "visibility")
        read_only_fields = fields

    def get_poster_url(self, obj) -> str | None:
        return asset_url(obj, obj.poster_path)


class VideoDetailSerializer(VideoCardSerializer):
    tags = TagSerializer(many=True, read_only=True)
    renditions = VideoRenditionSerializer(many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()
    is_following_uploader = serializers.SerializerMethodField()
    uploader_follower_count = serializers.IntegerField(
        source="uploader.follower_count", read_only=True
    )

    class Meta(VideoCardSerializer.Meta):
        fields = VideoCardSerializer.Meta.fields + (
            "description", "tags", "renditions", "source_resolution",
            "dislike_count", "comment_count", "status", "uploaded_at", "is_owner",
            "is_bookmarked", "is_following_uploader", "uploader_follower_count",
        )
        read_only_fields = fields

    def get_is_owner(self, obj) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated
                    and obj.uploader_id == request.user.pk)

    def get_is_bookmarked(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        from apps.library.models import Bookmark

        return Bookmark.objects.filter(user=request.user, video=obj).exists()

    def get_is_following_uploader(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        from apps.library.models import Follow

        return Follow.objects.filter(follower=request.user,
                                     channel_id=obj.uploader_id).exists()


class StudioVideoSerializer(serializers.ModelSerializer):
    """The uploader's own video. Exposes pipeline state; never used publicly."""

    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    renditions = VideoRenditionSerializer(many=True, read_only=True)
    poster_url = serializers.SerializerMethodField()
    stage_label = serializers.CharField(source="get_processing_stage_display",
                                        read_only=True)

    class Meta:
        model = Video
        fields = (
            "id", "title", "description", "status", "visibility", "category", "tags",
            "duration_seconds", "source_resolution", "poster_url", "renditions",
            "processing_stage", "stage_label", "processing_progress",
            "failure_reason", "transcode_attempts",
            "view_count", "like_count", "dislike_count", "comment_count",
            "original_filename", "original_size_bytes", "original_mime_type",
            "uploaded_at", "published_at", "updated_at",
        )
        read_only_fields = fields

    def get_poster_url(self, obj) -> str | None:
        return asset_url(obj, obj.poster_path)


class VideoUpdateSerializer(serializers.ModelSerializer):
    """Metadata edit. Deliberately narrow: status, counters and every storage
    path are server-owned and not addressable from here."""

    category_slug = serializers.SlugRelatedField(
        source="category", slug_field="slug", queryset=Category.objects.filter(is_active=True),
        required=False, allow_null=True,
    )
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False,
        allow_empty=True, write_only=True, max_length=15,
        help_text="Noms libres; normalises et dedupliques cote serveur.",
    )

    class Meta:
        model = Video
        fields = ("title", "description", "visibility", "category_slug", "tag_names")

    def validate(self, attrs):
        video = self.instance
        visibility = attrs.get("visibility")
        # Publishing a video that is still processing (or failed) would produce a
        # feed entry whose player has nothing to load.
        if (video and visibility and visibility != Visibility.PRIVATE
                and video.status != VideoStatus.READY):
            raise serializers.ValidationError(
                {"visibility": "Une video ne peut etre publiee qu'une fois prete."}
            )
        return attrs

    def update(self, instance, validated_data):
        tag_names = validated_data.pop("tag_names", None)
        previous_visibility = instance.visibility

        instance = super().update(instance, validated_data)

        if tag_names is not None:
            tags = Tag.resolve(tag_names)
            instance.tags.set(tags)
            # Keep the denormalised popularity counter honest.
            for tag in tags:
                Tag.objects.filter(pk=tag.pk).update(
                    usage_count=tag.videos.count()
                )

        # Stash for the view: a private <-> public switch must relocate the
        # objects between buckets, which is a Celery job, not a request one.
        instance._visibility_changed = (
            previous_visibility != instance.visibility
            and (previous_visibility == Visibility.PRIVATE)
            != (instance.visibility == Visibility.PRIVATE)
        )
        instance._previous_visibility = previous_visibility
        return instance


class StudioStatsSerializer(serializers.Serializer):
    """Response shape of `GET /api/studio/stats/` (documentation only).

    `engagement_available` stays part of the contract so the dashboard can tell
    the user whether the counters are live. It became `true` in Phase 3, when
    View/Like/Comment rows started backing them.
    """

    totals = serializers.DictField(child=serializers.IntegerField())
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_visibility = serializers.DictField(child=serializers.IntegerField())
    uploads_by_day = serializers.ListField(child=serializers.DictField())
    views_by_day = serializers.ListField(child=serializers.DictField())
    top_videos = serializers.ListField(child=serializers.DictField())
    engagement_available = serializers.BooleanField()


class PlaybackSerializer(serializers.Serializer):
    """Response shape of `POST /api/videos/<id>/playback/` (documentation only)."""

    delivery = serializers.ChoiceField(choices=["public", "signed"])
    master_url = serializers.URLField()
    poster_url = serializers.URLField(allow_null=True)
    sprite_url = serializers.URLField(allow_null=True)
    thumbnails_vtt_url = serializers.URLField(allow_null=True)
    sprite_meta = serializers.DictField(allow_null=True)
    duration_seconds = serializers.IntegerField()
    renditions = serializers.ListField(child=serializers.DictField())
    expires_in = serializers.IntegerField(allow_null=True)
