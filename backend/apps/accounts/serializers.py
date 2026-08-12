"""Account serializers (also wired into Djoser via settings.DJOSER.SERIALIZERS)."""
from django.contrib.auth.password_validation import validate_password
from djoser.serializers import UserCreatePasswordRetypeSerializer
from rest_framework import serializers

from apps.accounts.models import Role, User


class UserSerializer(serializers.ModelSerializer):
    """The authenticated user's own record."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "username", "display_name", "bio", "avatar", "avatar_url",
            "role", "is_active", "is_suspended", "preferred_language", "created_at",
        )
        read_only_fields = ("id", "email", "username", "role", "is_active",
                           "is_suspended", "created_at")

    def get_avatar_url(self, obj) -> str | None:
        return obj.avatar.url if obj.avatar else None


class PublicChannelSerializer(serializers.ModelSerializer):
    """A user as seen by anyone else — their channel identity. No email, ever."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "display_name", "bio", "avatar_url", "created_at")
        read_only_fields = fields

    def get_avatar_url(self, obj) -> str | None:
        return obj.avatar.url if obj.avatar else None


class UserCreateSerializer(UserCreatePasswordRetypeSerializer):
    """Public signup with password confirmation. Role is never client-settable.

    Subclasses the *retype* base, which injects `re_password` at runtime. Listing
    `re_password` in `Meta.fields` would make DRF try to build it from the model
    and raise ImproperlyConfigured, so it is deliberately absent here.
    """

    class Meta(UserCreatePasswordRetypeSerializer.Meta):
        model = User
        fields = ("id", "email", "username", "display_name", "password",
                  "preferred_language")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Defence in depth: strip any privilege fields a client tries to smuggle in.
        for forbidden in ("role", "is_staff", "is_superuser", "is_active"):
            attrs.pop(forbidden, None)
        return attrs

    def create(self, validated_data):
        validated_data["role"] = Role.USER
        return super().create(validated_data)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("display_name", "bio", "avatar", "preferred_language")


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Mot de passe actuel incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value
