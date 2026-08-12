"""Jazzmin admin skin configuration for StreamVerse (French-first)."""

JAZZMIN_SETTINGS = {
    "site_title": "StreamVerse Admin",
    "site_header": "StreamVerse",
    "site_brand": "StreamVerse",
    "site_logo": "img/streamverse-logo.svg",
    "login_logo": "img/streamverse-logo.svg",
    "site_logo_classes": "img-circle",
    "site_icon": "img/favicon.svg",
    "welcome_sign": "Bienvenue sur l'administration StreamVerse",
    "copyright": "StreamVerse",
    "search_model": ["videos.Video", "accounts.User"],
    "user_avatar": "avatar",

    "topmenu_links": [
        {"name": "Accueil", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Application", "url": "/", "new_window": True},
        {"name": "API Docs", "url": "/api/docs/", "new_window": True},
        {"name": "Flower", "url": "http://localhost:5574", "new_window": True},
    ],

    "usermenu_links": [
        {"name": "Documentation API", "url": "/api/docs/", "new_window": True},
    ],

    "show_sidebar": True,
    "navigation_expanded": False,

    # Side menu grouping. Apps not listed here still appear, at the bottom.
    "order_with_respect_to": [
        "videos",
        "catalog",
        "live",
        "engagement",
        "moderation",
        "monetization",
        "accounts",
        "audit",
        "auth",
        "django_celery_beat",
        "django_celery_results",
    ],

    "icons": {
        "accounts": "fas fa-users-cog",
        "accounts.User": "fas fa-user",
        "auth.Group": "fas fa-users",

        "catalog": "fas fa-sitemap",
        "catalog.Category": "fas fa-folder-open",
        "catalog.Tag": "fas fa-tag",

        "videos": "fas fa-photo-video",
        "videos.Video": "fas fa-film",
        "videos.VideoRendition": "fas fa-layer-group",
        "videos.VideoThumbnail": "fas fa-image",
        "videos.UploadSession": "fas fa-cloud-upload-alt",

        "library": "fas fa-bookmark",
        "library.Bookmark": "fas fa-star",
        "library.WatchHistoryEntry": "fas fa-history",
        "library.Follow": "fas fa-user-plus",

        "moderation": "fas fa-gavel",
        "moderation.ModerationAction": "fas fa-balance-scale",
        "moderation.UserSanction": "fas fa-user-slash",

        "monetization": "fas fa-coins",
        "monetization.SubscriptionPlan": "fas fa-crown",
        "monetization.UserSubscription": "fas fa-id-card",
        "monetization.Transaction": "fas fa-receipt",
        "monetization.WebhookEvent": "fas fa-satellite",
        "monetization.AdCampaign": "fas fa-bullhorn",
        "monetization.AdImpression": "fas fa-chart-line",

        "live": "fas fa-broadcast-tower",
        "live.LiveChannel": "fas fa-satellite-dish",
        "live.LiveRecording": "fas fa-record-vinyl",
        "live.LiveChatMessage": "fas fa-comment",

        "engagement": "fas fa-comments",
        "engagement.View": "fas fa-eye",
        "engagement.Like": "fas fa-thumbs-up",
        "engagement.Comment": "fas fa-comment-dots",
        "engagement.Report": "fas fa-flag",

        "audit": "fas fa-clipboard-list",
        "audit.AuditLog": "fas fa-history",

        "django_celery_beat": "fas fa-clock",
        "django_celery_results": "fas fa-tasks",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",

    "related_modal_active": True,
    "custom_css": "css/jazzmin-streamverse.css",
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        "auth.user": "collapsible",
        "auth.group": "vertical_tabs",
    },
    "language_chooser": False,
}

# Brand palette: indigo/violet accent on a dark sidebar.
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-indigo",
    "accent": "accent-indigo",
    "navbar": "navbar-dark",
    "no_navbar_border": True,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-indigo",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "flatly",
    # `dark_mode_theme` was removed in django-jazzmin 3.x: every theme now does
    # light/dark itself via `data-bs-theme`, and leaving the old key set only
    # produced a deprecation warning on every admin request.
    "default_theme_mode": "auto",
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}
