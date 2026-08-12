"""Engagement serializers."""
from __future__ import annotations

import bleach
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import PublicChannelSerializer
from apps.engagement.models import Comment, Like, Report, ReportReason, View
from apps.videos.models import Video

# Comments are rendered as plain text by the client, but stripping markup at the
# boundary means a future rich-text renderer cannot resurrect a stored payload.
ALLOWED_TAGS: list[str] = []


class CommentSerializer(serializers.ModelSerializer):
    author = PublicChannelSerializer(read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ("id", "video", "author", "content", "parent_comment",
                  "is_deleted", "reply_count", "replies", "can_edit", "can_delete",
                  "created_at", "updated_at")
        read_only_fields = ("id", "video", "author", "is_deleted", "reply_count",
                            "created_at", "updated_at")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_deleted:
            # Keep the node so replies stay attached, but never ship the text.
            data["content"] = ""
            data["author"] = None
        return data

    def get_can_edit(self, obj) -> bool:
        user = self.context.get("request").user if self.context.get("request") else None
        if not user or not user.is_authenticated or obj.is_deleted:
            return False
        return obj.author_id == user.pk

    def get_can_delete(self, obj) -> bool:
        user = self.context.get("request").user if self.context.get("request") else None
        if not user or not user.is_authenticated or obj.is_deleted:
            return False
        # Author, the video's uploader, or platform staff.
        return (obj.author_id == user.pk
                or obj.video.uploader_id == user.pk
                or user.is_staff_member)

    # Self-referential, so the type cannot be inferred; declared explicitly
    # rather than letting the schema default it to a bare string.
    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, obj):
        # Only populated on top-level nodes, and only when the view prefetched
        # them — otherwise this would be N+1 queries per comment.
        if obj.parent_comment_id is not None:
            return []
        replies = getattr(obj, "visible_replies", None)
        if replies is None:
            return []
        return CommentSerializer(replies, many=True, context=self.context).data


class CommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ("content", "parent_comment")

    def validate_content(self, value):
        cleaned = bleach.clean(value, tags=ALLOWED_TAGS, strip=True).strip()
        if not cleaned:
            raise serializers.ValidationError("Le commentaire ne peut pas etre vide.")
        return cleaned

    def validate_parent_comment(self, value):
        if value is None:
            return value
        video = self.context["video"]
        if value.video_id != video.pk:
            raise serializers.ValidationError(
                "Ce commentaire parent appartient a une autre video."
            )
        if value.parent_comment_id is not None:
            # One level only — a reply to a reply is flattened onto the thread
            # root rather than silently accepted and then rendered wrongly.
            raise serializers.ValidationError(
                "Les reponses sont limitees a un seul niveau."
            )
        if value.is_deleted:
            raise serializers.ValidationError(
                "Impossible de repondre a un commentaire supprime."
            )
        return value


class LikeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Like
        fields = ("video", "is_like", "created_at")
        read_only_fields = ("video", "created_at")


class LikeStateSerializer(serializers.Serializer):
    """Answer of the like/dislike toggle endpoint."""

    my_reaction = serializers.CharField(allow_null=True,
                                        help_text="like | dislike | null")
    like_count = serializers.IntegerField()
    dislike_count = serializers.IntegerField()


class ViewPingSerializer(serializers.Serializer):
    """Heartbeat from the player.

    `watched_seconds` is cumulative for the session, so an out-of-order or
    replayed ping cannot decrease the stored value.
    """

    watched_seconds = serializers.IntegerField(min_value=0, max_value=24 * 3600)
    client_id = serializers.CharField(max_length=64, required=False, allow_blank=True)


class ViewStateSerializer(serializers.Serializer):
    counted = serializers.BooleanField()
    watched_seconds = serializers.IntegerField()
    required_seconds = serializers.IntegerField()
    view_count = serializers.IntegerField()


class ReportSerializer(serializers.ModelSerializer):
    reporter = PublicChannelSerializer(read_only=True)
    target_type = serializers.SerializerMethodField()
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = ("id", "reporter", "target_type", "target_label", "reason",
                  "details", "status", "reviewed_at", "resolution_note",
                  "created_at")
        read_only_fields = fields

    def get_target_type(self, obj) -> str:
        return obj.content_type.model

    def get_target_label(self, obj) -> str:
        target = obj.target
        if target is None:
            return "(supprime)"
        return str(target)[:120]


class ReportCreateSerializer(serializers.Serializer):
    """Create a report against a video or a comment."""

    target_type = serializers.ChoiceField(choices=["video", "comment"])
    target_id = serializers.CharField(max_length=64)
    reason = serializers.ChoiceField(choices=ReportReason.choices)
    details = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, attrs):
        model = Video if attrs["target_type"] == "video" else Comment
        try:
            target = model.objects.get(pk=attrs["target_id"])
        except (model.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError(
                {"target_id": "Cible introuvable."}
            ) from None

        user = self.context["request"].user
        owner_id = target.uploader_id if model is Video else target.author_id
        if owner_id == user.pk:
            raise serializers.ValidationError(
                {"target_id": "Vous ne pouvez pas signaler votre propre contenu."}
            )

        attrs["target"] = target
        attrs["content_type"] = ContentType.objects.get_for_model(model)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        report, created = Report.objects.get_or_create(
            reporter=request.user,
            content_type=validated_data["content_type"],
            object_id=str(validated_data["target"].pk),
            status="pending",
            defaults={
                "reason": validated_data["reason"],
                "details": validated_data.get("details", ""),
            },
        )
        if not created:
            # The unique constraint already prevents duplicates; surface it as a
            # normal outcome rather than an integrity error.
            raise serializers.ValidationError(
                {"detail": "Vous avez deja signale ce contenu; "
                           "il est en cours d'examen."}
            )
        return report
