"""Account serializers (also wired into Djoser via settings.DJOSER.SERIALIZERS)."""
from django.contrib.auth.password_validation import validate_password
from djoser.serializers import UserCreatePasswordRetypeSerializer
from rest_framework import serializers

from apps.accounts.models import Role, User
from apps.accounts.validators import validate_profile_image


class ImageUrlMixin:
    """`avatar_url` / `banner_url` for any serializer over a User.

    Both images live in the public bucket, so `.url` is already an absolute,
    unsigned, browser-reachable URL — no request context needed to build it.
    """

    def get_avatar_url(self, obj) -> str | None:
        return obj.avatar.url if obj.avatar else None

    def get_banner_url(self, obj) -> str | None:
        return obj.banner.url if obj.banner else None


class UserSerializer(ImageUrlMixin, serializers.ModelSerializer):
    """The authenticated user's own record."""

    avatar_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "username", "display_name", "bio", "location",
            "website_url", "avatar_url", "banner_url", "role", "is_active",
            "is_suspended", "preferred_language", "created_at",
        )
        read_only_fields = ("id", "email", "username", "role", "is_active",
                           "is_suspended", "created_at")


class PublicChannelSerializer(ImageUrlMixin, serializers.ModelSerializer):
    """A user as seen by anyone else — their channel identity. No email, ever.

    Deliberately lean: this is nested in every video card, so a field added here
    is paid for once per card on every listing. Channel-page-only fields belong
    on `ChannelDetailSerializer`.
    """

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "display_name", "bio", "avatar_url", "created_at")
        read_only_fields = fields


class ChannelDetailSerializer(PublicChannelSerializer):
    """The channel page's own header — everything above, plus the decoration."""

    banner_url = serializers.SerializerMethodField()

    class Meta(PublicChannelSerializer.Meta):
        fields = PublicChannelSerializer.Meta.fields + (
            "banner_url", "location", "website_url",
        )
        read_only_fields = fields


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
    """The text half of the profile.

    Avatar and banner are handled by their own endpoints (see
    `ProfileImageView`): an image needs decode-level validation and has to clean
    up the object it replaces, and neither belongs in a JSON PATCH that a client
    may send with only `display_name` in it.
    """

    class Meta:
        model = User
        fields = ("display_name", "bio", "location", "website_url",
                  "preferred_language")

    def validate_website_url(self, value):
        # A profile link is rendered as an anchor on a public page; only the two
        # schemes a browser should navigate to are allowed. `javascript:` and
        # `data:` in particular must never reach an href.
        if value and not value.lower().startswith(("http://", "https://")):
            raise serializers.ValidationError(
                "Le lien doit commencer par http:// ou https://."
            )
        return value


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


class ProfileImageUploadSerializer(serializers.Serializer):
    """One image, for either `avatar` or `banner`.

    The caller puts the per-field limits in the context, so the same serializer
    covers both endpoints without a subclass each.
    """

    file = serializers.FileField(write_only=True)

    def validate_file(self, value):
        self.context["extension"] = validate_profile_image(
            value,
            max_bytes=self.context["max_bytes"],
            max_dimension=self.context["max_dimension"],
        )
        return value
