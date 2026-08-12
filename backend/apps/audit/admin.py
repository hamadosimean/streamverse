from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Strictly read-only: the audit trail is append-only by design."""

    list_display = ("created_at", "actor", "action", "object_repr", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("object_repr", "reason", "actor__username", "actor__email")
    date_hierarchy = "created_at"
    readonly_fields = ("actor", "action", "content_type", "object_id", "object_repr",
                       "reason", "metadata", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
