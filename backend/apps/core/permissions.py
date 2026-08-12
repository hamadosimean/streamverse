"""Role-based permission classes.

Roles are enforced server-side only; the frontend's role checks are UI affordance,
never the actual gate.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    message = "Reserve aux administrateurs."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsModerator(BasePermission):
    """Moderator *or* admin — admins inherit every moderator capability."""

    message = "Reserve aux moderateurs."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_moderator or user.is_admin))


class IsOwner(BasePermission):
    """Object-level ownership. Pair with a queryset that already filters by owner.

    `owner_field` on the view names the attribute holding the owning user.
    """

    message = "Vous n'etes pas proprietaire de cette ressource."

    def has_object_permission(self, request, view, obj):
        owner_field = getattr(view, "owner_field", "uploader")
        return getattr(obj, owner_field, None) == request.user


class IsOwnerOrReadOnly(IsOwner):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return super().has_object_permission(request, view, obj)


class IsOwnerOrStaff(IsOwner):
    """Owner, moderator or admin. Used where staff need override capability."""

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_authenticated and (user.is_admin or user.is_moderator):
            return True
        return super().has_object_permission(request, view, obj)
