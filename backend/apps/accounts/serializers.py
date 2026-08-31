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
    has_usable_password = serializers.SerializerMethodField()
    social_providers = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "username", "display_name", "bio", "location",
            "website_url", "avatar_url", "banner_url", "role", "is_active",
            "is_suspended", "preferred_language", "has_usable_password",
            "social_providers", "created_at",
        )
        read_only_fields = ("id", "email", "username", "role", "is_active",
                           "is_suspended", "created_at")

    def get_has_usable_password(self, obj) -> bool:
        """False for an account that only ever signed in through a provider.

        The account screen needs this to know whether to ask for the *current*
        password before setting a new one — there is nothing to ask for when
        the user has never had one.
        """
        return obj.has_usable_password()

    def get_social_providers(self, obj) -> list[str]:
        """Which external identities are linked, e.g. `["google"]`."""
        return sorted(link.provider for link in obj.social_accounts.all())


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
    """Change a password — or set the first one on a Google-only account.

    `current_password` is required exactly when there is a current password.
    A user who signed up through Google has an unusable one, and demanding it
    would lock them out of ever getting a local password at all.
    """

    current_password = serializers.CharField(write_only=True, required=False,
                                             allow_blank=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.has_usable_password():
            return attrs

        current = attrs.get("current_password")
        if not current:
            raise serializers.ValidationError(
                {"current_password": "Ce champ est obligatoire."}
            )
        if not user.check_password(current):
            raise serializers.ValidationError(
                {"current_password": "Mot de passe actuel incorrect."}
            )
        return attrs


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


# ---------------------------------------------------------------------------
# Google sign-in
#
# Plain Serializers, not ModelSerializers: none of these map to a table, and
# they exist as much for the generated OpenAPI schema as for validation.
# ---------------------------------------------------------------------------
class ProviderStateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class AuthProvidersSerializer(serializers.Serializer):
    google = ProviderStateSerializer()


class GoogleAuthorizeSerializer(serializers.Serializer):
    authorization_url = serializers.URLField(read_only=True)


class GoogleCallbackSerializer(serializers.Serializer):
    """What the SPA read out of Google's redirect and posted back to us."""

    code = serializers.CharField(write_only=True, trim_whitespace=True,
                                 max_length=2048)
    state = serializers.CharField(write_only=True, trim_whitespace=True,
                                  max_length=256)


class GoogleTokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    #: True on the sign-in that created the account, so the SPA can welcome a
    #: new user instead of greeting them back.
    created = serializers.BooleanField(read_only=True)
    #: Where to land, carried across the redirect and re-validated server-side.
    next = serializers.CharField(read_only=True)
