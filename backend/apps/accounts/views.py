"""Account endpoints beyond what Djoser provides."""
import logging
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import oauth
from apps.accounts.serializers import (
    AuthProvidersSerializer,
    ChannelDetailSerializer,
    GoogleAuthorizeSerializer,
    GoogleCallbackSerializer,
    GoogleTokenPairSerializer,
    PasswordChangeSerializer,
    ProfileImageUploadSerializer,
    ProfileUpdateSerializer,
    UserSerializer,
)
from apps.accounts.services import resolve_google_user

logger = logging.getLogger(__name__)

User = get_user_model()


@extend_schema(tags=["accounts"])
class MeView(generics.RetrieveUpdateAPIView):
    """Read or update the authenticated user's own profile."""

    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        return ProfileUpdateSerializer if self.request.method in ("PUT", "PATCH") else UserSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        # Always answer with the full representation the client caches.
        return Response(UserSerializer(request.user, context=self.get_serializer_context()).data)


@extend_schema(tags=["accounts"])
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data,
                                              context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password", "updated_at"])
        return Response({"detail": "Mot de passe mis a jour."},
                        status=status.HTTP_200_OK)


@extend_schema(tags=["accounts"])
class ProfileImageView(APIView):
    """Replace or remove one profile image (`avatar` or `banner`).

    PUT with `multipart/form-data` and a single `file` part; DELETE removes the
    current image. Both answer with the full user record, so the client can drop
    its cached copy in wholesale rather than patching a URL into it.

    A separate endpoint per image rather than a multipart PATCH on `me/`: the
    upload needs decode-level validation, and replacing an image has to delete
    the object it supersedes or the public bucket grows forever.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ProfileImageUploadSerializer

    #: Subclasses set the field they own and its limits.
    field_name: str = ""
    max_bytes_setting: str = ""
    max_dimension_setting: str = ""

    def _limits(self) -> dict:
        return {
            "max_bytes": getattr(settings, self.max_bytes_setting),
            "max_dimension": getattr(settings, self.max_dimension_setting),
        }

    def _respond(self, request) -> Response:
        return Response(UserSerializer(request.user, context={"request": request}).data)

    def _discard(self, old_file) -> None:
        """Drop the superseded object, but never at the cost of the request.

        The database row already points at the new image by the time this runs;
        a storage hiccup here leaves an orphan in the bucket, which is a cleanup
        problem, not a user-facing failure.
        """
        if not old_file:
            return
        try:
            old_file.storage.delete(old_file.name)
        except Exception:  # noqa: BLE001 - best effort, see docstring
            logger.warning("Could not delete superseded %s %r", self.field_name,
                           old_file.name, exc_info=True)

    @extend_schema(
        request={"multipart/form-data": {
            "type": "object",
            "properties": {"file": {"type": "string", "format": "binary"}},
            "required": ["file"],
        }},
        responses={200: UserSerializer},
    )
    def put(self, request, *args, **kwargs):
        serializer = ProfileImageUploadSerializer(
            data=request.data, context={"request": request, **self._limits()}
        )
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]

        user = request.user
        previous = getattr(user, self.field_name)
        previous = previous if previous else None

        # The stored name is ours, not the client's: an uploaded filename is
        # attacker-controlled text, and the extension comes from what Pillow
        # actually decoded rather than from what the name claimed.
        filename = f"{user.pk}-{uuid.uuid4().hex[:12]}{serializer.context['extension']}"
        getattr(user, self.field_name).save(filename, upload, save=False)
        user.save(update_fields=[self.field_name, "updated_at"])

        self._discard(previous)
        return self._respond(request)

    @extend_schema(responses={200: UserSerializer,
                              404: OpenApiResponse(description="Aucune image a retirer.")})
    def delete(self, request, *args, **kwargs):
        user = request.user
        current = getattr(user, self.field_name)
        if not current:
            return Response({"detail": "Aucune image a retirer."},
                            status=status.HTTP_404_NOT_FOUND)

        setattr(user, self.field_name, None)
        user.save(update_fields=[self.field_name, "updated_at"])
        self._discard(current)
        return self._respond(request)


class AvatarView(ProfileImageView):
    field_name = "avatar"
    max_bytes_setting = "MAX_AVATAR_BYTES"
    max_dimension_setting = "MAX_AVATAR_DIMENSION"


class BannerView(ProfileImageView):
    field_name = "banner"
    max_bytes_setting = "MAX_BANNER_BYTES"
    max_dimension_setting = "MAX_BANNER_DIMENSION"


@extend_schema(tags=["accounts"])
class PublicChannelView(generics.RetrieveAPIView):
    """A user's public channel: identity plus aggregate stats.

    No subscribe/follow button and no new-video notifications — browsing is
    follow-less in v1, per scope. The aggregates below are computed over the
    channel's *public, ready* videos only, so a private upload never leaks its
    existence through a count.
    """

    permission_classes = [AllowAny]
    serializer_class = ChannelDetailSerializer
    lookup_field = "username"

    def get_queryset(self):
        return User.objects.filter(is_active=True, is_suspended=False)

    def retrieve(self, request, *args, **kwargs):
        from django.db.models import Count, Sum

        from apps.videos.models import Video

        user = self.get_object()
        data = self.get_serializer(user).data

        stats = Video.objects.publicly_listed().filter(uploader=user).aggregate(
            video_count=Count("id"),
            total_views=Sum("view_count"),
            total_likes=Sum("like_count"),
            total_duration=Sum("duration_seconds"),
        )
        data["stats"] = {
            "video_count": stats["video_count"] or 0,
            "total_views": stats["total_views"] or 0,
            "total_likes": stats["total_likes"] or 0,
            "total_duration_seconds": stats["total_duration"] or 0,
            "follower_count": user.follower_count,
        }

        # Whether *the caller* follows this channel — never whether anyone does.
        from apps.library.models import Follow

        data["is_following"] = (
            request.user.is_authenticated
            and Follow.objects.filter(follower=request.user, channel=user).exists()
        )
        data["is_self"] = request.user.is_authenticated and request.user.pk == user.pk
        return Response(data)


@extend_schema(tags=["accounts"])
class ChannelVideosView(generics.ListAPIView):
    """A channel's public videos.

    Only `ready` + `public` rows: unlisted videos are reachable by direct link
    only, and listing them on a channel page would defeat that.
    """

    permission_classes = [AllowAny]

    def get_serializer_class(self):
        from apps.videos.serializers import VideoCardSerializer

        return VideoCardSerializer

    def get_queryset(self):
        from apps.videos.models import Video

        # Schema generation instantiates the view without URL kwargs.
        if getattr(self, "swagger_fake_view", False):
            return Video.objects.none()

        user = get_object_or_404(
            User.objects.filter(is_active=True, is_suspended=False),
            username=self.kwargs["username"],
        )

        sort = self.request.query_params.get("sort", "recent")
        ordering = {
            "recent": ("-published_at",),
            "popular": ("-view_count", "-published_at"),
            "oldest": ("published_at",),
        }.get(sort, ("-published_at",))

        return (
            Video.objects.publicly_listed()
            .filter(uploader=user)
            .with_related()
            .order_by(*ordering)
        )


# ---------------------------------------------------------------------------
# Google sign-in
#
# The protocol lives in apps.accounts.oauth and the user resolution in
# apps.accounts.services; what is left here is the HTTP shape and the mapping
# from a GoogleAuthError to a status code.
# ---------------------------------------------------------------------------
def _oauth_error_response(exc: oauth.GoogleAuthError) -> Response:
    status_code = {
        "not_configured": status.HTTP_503_SERVICE_UNAVAILABLE,
        # Wrong credentials are as unusable as absent ones, and neither is
        # something the caller can fix by retrying.
        "client_misconfigured": status.HTTP_503_SERVICE_UNAVAILABLE,
        "provider_unreachable": status.HTTP_502_BAD_GATEWAY,
        "account_suspended": status.HTTP_403_FORBIDDEN,
    }.get(exc.code, status.HTTP_400_BAD_REQUEST)
    # Hand-built rather than raised, so it matches the envelope every other
    # error goes through (apps.core.exceptions.api_exception_handler).
    return Response({"detail": exc.message, "code": exc.code, "errors": None},
                    status=status_code)


@extend_schema(tags=["auth"])
class AuthProvidersView(APIView):
    """Which sign-in methods this deployment actually offers.

    The Google button is only worth rendering if the deployment has credentials
    for it. Asking the server beats a second copy of the same fact in the
    frontend's build-time env, which would silently drift.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = AuthProvidersSerializer

    @extend_schema(responses={200: AuthProvidersSerializer})
    def get(self, request):
        return Response({"google": {"enabled": oauth.is_configured()}})


@extend_schema(tags=["auth"])
class GoogleAuthorizeView(APIView):
    """Start the flow: hand the SPA the URL to send the browser to.

    A JSON payload rather than a 302, because the caller is `fetch`/axios — a
    redirect here would be followed by the XHR layer and Google would answer a
    cross-origin request the browser then refuses to read.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"
    serializer_class = GoogleAuthorizeSerializer

    @extend_schema(
        parameters=[OpenApiParameter(
            "next", str, description="Chemin relatif ou revenir apres connexion.",
        )],
        responses={200: GoogleAuthorizeSerializer,
                   503: OpenApiResponse(description="Google n'est pas configure.")},
    )
    def get(self, request):
        try:
            url = oauth.build_authorization_url(
                next_path=request.query_params.get("next", "/")
            )
        except oauth.GoogleAuthError as exc:
            return _oauth_error_response(exc)
        return Response({"authorization_url": url})


@extend_schema(tags=["auth"])
class GoogleCallbackView(APIView):
    """Finish the flow: code + state in, our own JWT pair out.

    POST rather than GET even though the browser arrives back via a redirect:
    the SPA owns the callback route, reads the query string itself, and posts it
    here. That keeps the authorization code out of the Referer header and out of
    any server access log that records query strings.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"
    serializer_class = GoogleCallbackSerializer

    @extend_schema(request=GoogleCallbackSerializer,
                   responses={200: GoogleTokenPairSerializer})
    def post(self, request):
        serializer = GoogleCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            identity, next_path = oauth.complete(**serializer.validated_data)
            user, created = resolve_google_user(identity)
        except oauth.GoogleAuthError as exc:
            return _oauth_error_response(exc)

        refresh = RefreshToken.for_user(user)
        update_last_login(None, user)
        logger.info("Google sign-in for user %s (created=%s)", user.pk, created)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "created": created,
            "next": next_path,
        })
