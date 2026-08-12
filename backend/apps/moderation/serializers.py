"""Moderation serializers.

The queue payload is deliberately rich: a moderator deciding on a report needs
the reported content, who made it, how many others reported the same thing, and
whether this author has been actioned before — all without leaving the row.
Making them click through for context is how bad decisions get made quickly.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import PublicChannelSerializer
from apps.engagement.models import Comment, Report
from apps.moderation.models import ModerationAction, UserSanction
from apps.videos.models import Video


class ReportTargetSerializer(serializers.Serializer):
    """The reported object, flattened to what a moderator needs to judge it."""

    type = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    author = PublicChannelSerializer(allow_null=True)
    url = serializers.CharField(allow_blank=True)
    poster_url = serializers.CharField(allow_null=True, required=False)
    already_removed = serializers.BooleanField()


def describe_target(report: Report) -> dict | None:
    target = report.target
    if target is None:
        return None

    if isinstance(target, Video):
        from apps.videos.serializers import asset_url

        return {
            "type": "video",
            "id": str(target.pk),
            "title": target.title,
            "body": target.description or "",
            "author": PublicChannelSerializer(target.uploader).data,
            "url": f"/watch/{target.pk}",
            "poster_url": asset_url(target, target.poster_path),
            "already_removed": target.status == "taken_down",
        }

    if isinstance(target, Comment):
        return {
            "type": "comment",
            "id": str(target.pk),
            "title": f"Commentaire sur « {target.video.title} »",
            "body": target.content,
            "author": PublicChannelSerializer(target.author).data,
            "url": f"/watch/{target.video_id}",
            "poster_url": None,
            "already_removed": target.is_deleted,
        }

    return None


class ModerationReportSerializer(serializers.ModelSerializer):
    reporter = PublicChannelSerializer(read_only=True)
    reviewed_by = PublicChannelSerializer(read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    target = serializers.SerializerMethodField()
    duplicate_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Report
        fields = ("id", "reporter", "reason", "reason_label", "details", "status",
                  "reviewed_by", "reviewed_at", "resolution_note", "created_at",
                  "target", "duplicate_count")
        read_only_fields = fields

    def get_target(self, obj) -> dict | None:
        return describe_target(obj)


class ResolveReportSerializer(serializers.Serializer):
    """A moderation decision.

    `reason` is required for every action except `dismiss`, and validated here
    as well as in the service — content that vanishes without a stated reason is
    how a moderation system loses the trust of the people it moderates.
    """

    action = serializers.ChoiceField(
        choices=["dismiss", "remove", "remove_and_warn", "remove_and_suspend"]
    )
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    suspend_days = serializers.IntegerField(min_value=1, max_value=3650,
                                            required=False)

    def validate(self, attrs):
        if attrs["action"] != "dismiss":
            reason = (attrs.get("reason") or "").strip()
            if len(reason) < 10:
                raise serializers.ValidationError({
                    "reason": "Un motif d'au moins 10 caracteres est obligatoire "
                              "pour un retrait: il est communique a l'auteur."
                })
            attrs["reason"] = reason
        return attrs


class ModerationActionSerializer(serializers.ModelSerializer):
    moderator = PublicChannelSerializer(read_only=True)
    affected_user = PublicChannelSerializer(read_only=True)
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = ModerationAction
        fields = ("id", "moderator", "action", "action_label", "target_repr",
                  "affected_user", "reason", "report", "metadata", "created_at")
        read_only_fields = fields


class UserSanctionSerializer(serializers.ModelSerializer):
    user = PublicChannelSerializer(read_only=True)
    moderator = PublicChannelSerializer(read_only=True)
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserSanction
        fields = ("id", "user", "moderator", "type", "type_label", "reason",
                  "starts_at", "expires_at", "lifted_at", "is_active", "created_at")
        read_only_fields = fields


class SanctionCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=30)
    action = serializers.ChoiceField(choices=["warn", "suspend", "ban", "reinstate"])
    reason = serializers.CharField(max_length=2000)
    days = serializers.IntegerField(min_value=1, max_value=3650, required=False,
                                    default=7)

    def validate_reason(self, value):
        if len((value or "").strip()) < 10:
            raise serializers.ValidationError(
                "Un motif d'au moins 10 caracteres est obligatoire."
            )
        return value.strip()
