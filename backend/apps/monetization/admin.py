"""Django admin for monetization.

Ad-campaign *management* is a dedicated React view, because approving, pausing
and capping campaigns is a decision workflow rather than row editing. What lives
here is the read-only ledger: transactions, webhook events and subscriptions,
where an operator needs to look something up rather than change it.
"""
from django.contrib import admin
from django.utils.html import format_html

from apps.monetization.models import (
    AdCampaign,
    AdImpression,
    SubscriptionPlan,
    Transaction,
    UserSubscription,
    WebhookEvent,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_display", "billing_period", "ad_free",
                    "is_active", "display_order")
    list_editable = ("is_active", "display_order")
    list_filter = ("is_active", "billing_period", "ad_free")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Prix", ordering="price")
    def price_display(self, obj):
        return f"{obj.price:,} FCFA".replace(",", " ")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status_badge", "current_period_end",
                    "auto_renew", "created_at")
    list_filter = ("status", "auto_renew", "plan")
    search_fields = ("user__username", "user__email")
    date_hierarchy = "created_at"
    list_select_related = ("user", "plan")
    readonly_fields = ("user", "plan", "status", "started_at", "current_period_end",
                       "cancelled_at", "renewal_failures", "created_at", "updated_at")

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {"active": "#10b981", "pending": "#f59e0b",
                  "cancelled": "#6b7280", "expired": "#ef4444"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"), obj.get_status_display(),
        )


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Strictly read-only. A payment ledger that an admin can hand-edit is not a
    ledger — corrections belong in a new transaction, not an altered one."""

    list_display = ("created_at", "user", "amount_display", "provider",
                    "type", "status_badge", "completed_at")
    list_filter = ("status", "provider", "type", "created_at")
    search_fields = ("user__username", "user__email", "provider_reference",
                     "idempotency_key", "id")
    date_hierarchy = "created_at"
    list_select_related = ("user", "plan")
    readonly_fields = [f.name for f in Transaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Montant", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.amount:,} FCFA".replace(",", " ")

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {"completed": "#10b981", "pending": "#f59e0b",
                  "failed": "#ef4444", "cancelled": "#6b7280"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"), obj.get_status_display(),
        )


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("received_at", "provider", "event_type", "event_id",
                    "signature_valid", "processed", "has_error")
    list_filter = ("provider", "processed", "signature_valid", "received_at")
    search_fields = ("event_id", "processing_error")
    date_hierarchy = "received_at"
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Erreur", boolean=True)
    def has_error(self, obj):
        return bool(obj.processing_error)


@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    """Reference view. Day-to-day campaign work happens in /admin/ads."""

    list_display = ("advertiser_name", "title", "placement", "status",
                    "impression_progress", "click_count", "end_date")
    list_filter = ("status", "placement", "start_date")
    search_fields = ("advertiser_name", "title")
    autocomplete_fields = ("categories", "created_by")
    readonly_fields = ("impression_count", "completed_count", "click_count",
                       "created_at", "updated_at")

    @admin.display(description="Impressions")
    def impression_progress(self, obj):
        if obj.impression_cap:
            percent = min(100, int(obj.impression_count * 100 / obj.impression_cap))
            return format_html(
                '{} / {} ({}%)', obj.impression_count, obj.impression_cap, percent
            )
        return f"{obj.impression_count} (illimite)"


@admin.register(AdImpression)
class AdImpressionAdmin(admin.ModelAdmin):
    list_display = ("played_at", "campaign", "video", "placement", "completed",
                    "skipped", "clicked")
    list_filter = ("placement", "completed", "skipped", "clicked", "played_at")
    search_fields = ("campaign__title", "video__title")
    date_hierarchy = "played_at"
    list_select_related = ("campaign", "video")
    readonly_fields = [f.name for f in AdImpression._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
