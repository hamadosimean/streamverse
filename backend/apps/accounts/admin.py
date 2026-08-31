from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import SocialAccount, User


class SocialAccountInline(admin.TabularInline):
    """Which external logins reach this account, visible from the user page.

    Read-only: a link is created by a completed OAuth handshake and nothing
    else. Typing a `sub` in by hand would hand someone else's Google account
    the keys to this one.
    """

    model = SocialAccount
    extra = 0
    can_delete = True
    fields = ("provider", "subject", "email", "last_used_at", "created_at")
    readonly_fields = fields


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "username", "display_name", "role", "is_active",
                    "is_suspended", "created_at")
    list_filter = ("role", "is_active", "is_suspended", "is_staff", "preferred_language")
    search_fields = ("email", "username", "display_name")
    readonly_fields = ("created_at", "updated_at", "last_login", "suspended_at")
    inlines = (SocialAccountInline,)

    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        (_("Profil"), {"fields": ("display_name", "bio", "avatar", "banner",
                                  "location", "website_url",
                                  "preferred_language")}),
        (_("Role et acces"), {"fields": ("role", "is_active", "is_staff",
                                         "is_superuser", "groups",
                                         "user_permissions")}),
        (_("Moderation"), {"fields": ("is_suspended", "suspension_reason",
                                      "suspended_at")}),
        (_("Dates"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "display_name", "role",
                       "password1", "password2", "is_active"),
        }),
    )


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    """Standalone view, for answering "who owns this Google account?"."""

    list_display = ("provider", "email", "user", "last_used_at", "created_at")
    list_filter = ("provider",)
    search_fields = ("email", "subject", "user__email", "user__username")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at", "last_used_at")
