"""Account endpoints beyond what Djoser provides."""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import (
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    PublicChannelSerializer,
    UserSerializer,
)

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
class PublicChannelView(generics.RetrieveAPIView):
    """A user's public channel: identity plus aggregate stats.

    No subscribe/follow button and no new-video notifications — browsing is
    follow-less in v1, per scope. The aggregates below are computed over the
    channel's *public, ready* videos only, so a private upload never leaks its
    existence through a count.
    """

    permission_classes = [AllowAny]
    serializer_class = PublicChannelSerializer
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
