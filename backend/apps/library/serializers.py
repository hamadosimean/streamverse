"""Library serializers."""
from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import PublicChannelSerializer
from apps.library.models import Bookmark, Follow, WatchHistoryEntry
from apps.videos.serializers import VideoCardSerializer


class WatchHistoryEntrySerializer(serializers.ModelSerializer):
    video = VideoCardSerializer(read_only=True)
    progress_percent = serializers.IntegerField(read_only=True)
    is_resumable = serializers.BooleanField(read_only=True)

    class Meta:
        model = WatchHistoryEntry
        fields = ("video", "progress_seconds", "progress_percent", "is_resumable",
                  "completed", "watch_count", "first_watched_at", "last_watched_at")
        read_only_fields = fields


class BookmarkSerializer(serializers.ModelSerializer):
    video = VideoCardSerializer(read_only=True)

    class Meta:
        model = Bookmark
        fields = ("video", "note", "created_at")
        read_only_fields = ("video", "created_at")


class FollowedChannelSerializer(serializers.ModelSerializer):
    """A channel the caller follows, with just enough to render a row."""

    channel = PublicChannelSerializer(read_only=True)
    follower_count = serializers.IntegerField(source="channel.follower_count",
                                              read_only=True)
    video_count = serializers.IntegerField(read_only=True, default=0)
    latest_video_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Follow
        fields = ("channel", "follower_count", "video_count", "latest_video_at",
                  "created_at")
        read_only_fields = fields


class FollowStateSerializer(serializers.Serializer):
    """Answer of the follow toggle."""

    is_following = serializers.BooleanField()
    follower_count = serializers.IntegerField()


class BookmarkStateSerializer(serializers.Serializer):
    is_bookmarked = serializers.BooleanField()


class LibraryVideoSerializer(VideoCardSerializer):
    """A video card carrying the caller's own state.

    `is_bookmarked` and `my_reaction` are filled from maps the view builds in two
    queries for the whole page — never per row.
    """

    is_bookmarked = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()

    class Meta(VideoCardSerializer.Meta):
        fields = VideoCardSerializer.Meta.fields + ("is_bookmarked", "my_reaction")
        read_only_fields = fields

    def get_is_bookmarked(self, obj) -> bool:
        return obj.pk in (self.context.get("bookmarked") or set())

    def get_my_reaction(self, obj) -> str | None:
        reactions = self.context.get("reactions") or {}
        if obj.pk not in reactions:
            return None
        return "like" if reactions[obj.pk] else "dislike"
