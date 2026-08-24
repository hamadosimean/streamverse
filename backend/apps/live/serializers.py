"""Live serializers.

Two channel shapes, because a stream key must never reach anyone but its owner:
`PublicLiveChannelSerializer` has no credential fields at all, and
`OwnerLiveChannelSerializer` is only ever instantiated for `request.user`'s own
channel.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.accounts.serializers import PublicChannelSerializer
from apps.catalog.serializers import CategorySerializer
from apps.live.models import LiveChannel, LiveChatMessage, LiveRecording


def hls_url(channel: LiveChannel) -> str:
    """Viewer-facing HLS URL, proxied by nginx.

    Same-origin on purpose: it avoids a CORS preflight per segment and keeps
    MediaMTX off the public port list.
    """
    return f"{settings.LIVE_HLS_PUBLIC_PATH}/{channel.rtmp_path}/index.m3u8"


class PublicLiveChannelSerializer(serializers.ModelSerializer):
    user = PublicChannelSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    playback_url = serializers.SerializerMethodField()

    class Meta:
        model = LiveChannel
        fields = ("slug", "title", "description", "user", "category", "status",
                  "started_at", "ended_at", "current_viewer_count",
                  "peak_viewer_count", "chat_enabled", "playback_url")
        read_only_fields = fields

    def get_playback_url(self, obj) -> str | None:
        # Only offered while actually live; a manifest URL for an offline
        # channel would just 404 in the player.
        return hls_url(obj) if obj.is_live else None


class OwnerLiveChannelSerializer(serializers.ModelSerializer):
    """The owner's view. The only serializer that ever exposes the stream key."""

    category_slug = serializers.SlugRelatedField(
        source="category", slug_field="slug", required=False, allow_null=True,
        queryset=CategorySerializer.Meta.model.objects.filter(is_active=True),
    )
    playback_url = serializers.SerializerMethodField()
    ingest_url = serializers.SerializerMethodField()
    obs_stream_key = serializers.SerializerMethodField()
    can_broadcast_from_browser = serializers.SerializerMethodField()

    class Meta:
        model = LiveChannel
        fields = ("slug", "title", "description", "category_slug", "status",
                  "stream_key", "stream_key_rotated_at", "ingest_url",
                  "obs_stream_key", "can_broadcast_from_browser",
                  "playback_url", "started_at", "ended_at",
                  "current_viewer_count", "peak_viewer_count",
                  "all_time_peak_viewers", "total_sessions", "chat_enabled",
                  "record_sessions", "is_enabled")
        read_only_fields = ("slug", "status", "stream_key", "stream_key_rotated_at",
                            "started_at", "ended_at", "current_viewer_count",
                            "peak_viewer_count", "all_time_peak_viewers",
                            "total_sessions", "is_enabled")

    def get_playback_url(self, obj) -> str | None:
        return hls_url(obj) if obj.is_live else None

    def get_ingest_url(self, obj) -> str:
        """What goes in OBS's *Server* field."""
        return f"{settings.LIVE_RTMP_PUBLIC_URL}/{settings.LIVE_RTMP_APP}"

    def get_can_broadcast_from_browser(self, obj) -> bool:
        """Whether the studio should offer the camera panel at all.

        No publish URL is handed out here: that needs a ticket, which is minted
        only when the user actually presses *go live*.
        """
        return bool(obj.is_enabled and not obj.user.is_suspended)

    def get_obs_stream_key(self, obj) -> str:
        """What goes in OBS's *Stream Key* field.

        The slug is the path and the secret rides in the query string — so the
        HLS URL handed to viewers never contains the key.
        """
        return f"{obj.slug}?key={obj.stream_key}"


class LiveChatMessageSerializer(serializers.ModelSerializer):
    user = PublicChannelSerializer(read_only=True)

    class Meta:
        model = LiveChatMessage
        fields = ("id", "user", "content", "created_at")
        read_only_fields = fields


class LiveRecordingSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.IntegerField(read_only=True)
    converted_video_id = serializers.SerializerMethodField()

    class Meta:
        model = LiveRecording
        fields = ("id", "started_at", "ended_at", "duration_seconds",
                  "peak_viewer_count", "chat_message_count", "recorded_size_bytes",
                  "converted_video_id", "conversion_error")
        read_only_fields = fields

    def get_converted_video_id(self, obj) -> str | None:
        return str(obj.converted_video_id) if obj.converted_video_id else None


class MediaMTXAuthSerializer(serializers.Serializer):
    """The body MediaMTX posts to the auth endpoint."""

    action = serializers.CharField()
    path = serializers.CharField(allow_blank=True)
    query = serializers.CharField(allow_blank=True, required=False, default="")
    protocol = serializers.CharField(allow_blank=True, required=False, default="")
    ip = serializers.CharField(allow_blank=True, required=False, default="")
    user = serializers.CharField(allow_blank=True, required=False, default="")
    password = serializers.CharField(allow_blank=True, required=False, default="")
    id = serializers.CharField(allow_blank=True, required=False, default="")
    token = serializers.CharField(allow_blank=True, required=False, default="")
