"""
Django settings for StreamVerse.

Everything environment-driven (see `.env.example`). Nothing secret is hardcoded.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR.parent / ".env")

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    # Jazzmin must precede django.contrib.admin to override its templates.
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # full-text search (Phase 3) + array/JSON helpers
    "django.contrib.sitemaps",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "djoser",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "channels",
    "django_celery_beat",
    "django_celery_results",
    "django_cleanup.apps.CleanupConfig",
    # Local
    "apps.core",
    "apps.seo",
    "apps.audit",
    "apps.accounts",
    "apps.catalog",
    "apps.videos",
    "apps.engagement",
    "apps.search",
    "apps.live",
    "apps.monetization",
    "apps.moderation",
    "apps.library",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="streamverse"),
        "USER": env("POSTGRES_USER", default="streamverse"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="streamverse"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": 60,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# i18n — French is the default UI language, English is secondary.
# --------------------------------------------------------------------------
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Francais"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static / media
#
# Video media does NOT go through Django's MEDIA_ROOT — it lives in MinIO and is
# served straight from MinIO to the browser (see apps/core/storage.py and
# apps/videos/services/playback.py). MEDIA_* only backs small FileFields such as
# avatars and (Phase 5) ad creatives.
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"

# --------------------------------------------------------------------------
# MinIO / S3-compatible object storage
#
# Two endpoints on purpose:
#   INTERNAL — what Django/Celery use inside the compose network (http://minio:9000)
#   PUBLIC   — what the *browser* uses (http://localhost:9010)
# Presigned URLs must be signed against the PUBLIC host, or the SigV4 signature
# will not match the Host header the browser actually sends.
# --------------------------------------------------------------------------
MINIO_ENDPOINT = env("MINIO_ENDPOINT", default="http://minio:9000")
MINIO_PUBLIC_ENDPOINT = env("MINIO_PUBLIC_ENDPOINT", default="http://localhost:9010")
MINIO_ACCESS_KEY = env("MINIO_ACCESS_KEY", default="streamverse")
MINIO_SECRET_KEY = env("MINIO_SECRET_KEY", default="streamverse-secret")
MINIO_REGION = env("MINIO_REGION", default="us-east-1")
MINIO_PUBLIC_BUCKET = env("MINIO_PUBLIC_BUCKET", default="streamverse-public")
MINIO_PRIVATE_BUCKET = env("MINIO_PRIVATE_BUCKET", default="streamverse-private")

# TTL for presigned URLs handed to the player for private content.
MINIO_PRESIGN_TTL_SECONDS = env.int("MINIO_PRESIGN_TTL_SECONDS", default=6 * 3600)

_S3_COMMON = {
    "access_key": MINIO_ACCESS_KEY,
    "secret_key": MINIO_SECRET_KEY,
    "endpoint_url": MINIO_ENDPOINT,
    "region_name": MINIO_REGION,
    "addressing_style": "path",  # MinIO does not do virtual-host buckets by default
    "file_overwrite": False,
    "signature_version": "s3v4",
}

STORAGES = {
    # Default (private) storage for FileFields that must not be world-readable.
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {**_S3_COMMON, "bucket_name": MINIO_PRIVATE_BUCKET,
                    "querystring_auth": True,
                    "querystring_expire": MINIO_PRESIGN_TTL_SECONDS},
    },
    # Opt-in public storage (avatars, ad creatives) — anonymous read.
    "public": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {**_S3_COMMON, "bucket_name": MINIO_PUBLIC_BUCKET,
                    "querystring_auth": False,
                    "custom_domain": MINIO_PUBLIC_ENDPOINT.split("://", 1)[-1]
                                     + "/" + MINIO_PUBLIC_BUCKET,
                    "url_protocol": MINIO_PUBLIC_ENDPOINT.split("://", 1)[0] + ":"},
    },
    "staticfiles": {
        # Not WhiteNoise's class directly — Jazzmin calls {% static %} on a
        # directory, which a strict manifest cannot resolve. See the module
        # docstring; without this every admin page is a 500.
        "BACKEND": "apps.core.staticfiles.AdminFriendlyManifestStaticFilesStorage",
    },
}

# --------------------------------------------------------------------------
# Upload pipeline (tus) — see apps/videos/tus.py
# --------------------------------------------------------------------------
UPLOAD_SCRATCH_DIR = Path(env("UPLOAD_SCRATCH_DIR", default="/data/uploads"))
TRANSCODE_WORK_DIR = Path(env("TRANSCODE_WORK_DIR", default="/data/work"))
MAX_UPLOAD_BYTES = env.int("MAX_UPLOAD_BYTES", default=5 * 1024 * 1024 * 1024)  # 5 GiB
MAX_VIDEO_DURATION_SECONDS = env.int("MAX_VIDEO_DURATION_SECONDS", default=4 * 3600)
ALLOWED_VIDEO_MIME_TYPES = [
    "video/mp4", "video/quicktime", "video/x-matroska", "video/webm",
    "video/x-msvideo", "video/mpeg", "video/3gpp", "video/x-flv",
]
# Abandoned tus sessions older than this are swept by a beat task.
UPLOAD_SESSION_TTL_HOURS = env.int("UPLOAD_SESSION_TTL_HOURS", default=24)

# --------------------------------------------------------------------------
# Profile images (avatar + channel banner)
#
# These are small, world-readable images that live in the PUBLIC bucket, so the
# limits are about keeping a page cheap to render rather than about disk. The
# dimension ceilings are enforced server-side: a browser can be told to resize
# before upload, but never trusted to have done it.
# --------------------------------------------------------------------------
ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]
MAX_AVATAR_BYTES = env.int("MAX_AVATAR_BYTES", default=5 * 1024 * 1024)      # 5 MiB
MAX_BANNER_BYTES = env.int("MAX_BANNER_BYTES", default=10 * 1024 * 1024)     # 10 MiB
MAX_AVATAR_DIMENSION = env.int("MAX_AVATAR_DIMENSION", default=2048)
MAX_BANNER_DIMENSION = env.int("MAX_BANNER_DIMENSION", default=6000)

# --------------------------------------------------------------------------
# Engagement & search (Phase 3)
# --------------------------------------------------------------------------
# A view only counts after this much watch time — or 30% of the video, whichever
# is smaller, so short clips remain countable. Enforced server-side.
VIEW_MIN_SECONDS = env.int("VIEW_MIN_SECONDS", default=30)
# Repeat views by the same identity inside this window collapse into one row.
VIEW_DEDUP_WINDOW_SECONDS = env.int("VIEW_DEDUP_WINDOW_SECONDS", default=12 * 3600)
# PostgreSQL text-search dictionary. 'french' stems French; use 'simple' for a
# mixed-language catalogue where stemming does more harm than good.
SEARCH_LANGUAGE_CONFIG = env("SEARCH_LANGUAGE_CONFIG", default="french")

# --------------------------------------------------------------------------
# Live streaming (Phase 4) — MediaMTX RTMP ingest
# --------------------------------------------------------------------------
# RTMP application segment. The full MediaMTX path is `<app>/<channel-slug>`;
# the stream key travels in the query string, NEVER in the path, because the
# path is what appears in the HLS URL every viewer fetches.
LIVE_RTMP_APP = env("LIVE_RTMP_APP", default="live")
# What the broadcaster types into OBS's "Server" field.
LIVE_RTMP_PUBLIC_URL = env("LIVE_RTMP_PUBLIC_URL", default="rtmp://localhost:1936")
# Same-origin path where nginx proxies MediaMTX's HLS output.
LIVE_HLS_PUBLIC_PATH = env("LIVE_HLS_PUBLIC_PATH", default="/live-hls")

# --- Going live from a browser (WebRTC/WHIP) -------------------------------
# A browser publishes to `<webrtc-app>/<slug>`, where an ffmpeg bridge inside
# MediaMTX re-encodes the Opus audio to AAC and republishes to `live/<slug>`.
# The staging path is separate so the channel only flips to `live` once the
# stream viewers can actually play exists. See mediamtx/bridge.sh.
LIVE_WEBRTC_APP = env("LIVE_WEBRTC_APP", default="webrtc")
# Same-origin path where nginx proxies MediaMTX's WHIP endpoint.
LIVE_WEBRTC_PUBLIC_PATH = env("LIVE_WEBRTC_PUBLIC_PATH", default="/live-webrtc")
# A browser publish is authorised by a short-lived ticket rather than the
# channel's permanent stream key: the key would end up in a URL, in MediaMTX's
# logs and in the browser's history for a credential that never expires.
LIVE_WHIP_TICKET_TTL_SECONDS = env.int("LIVE_WHIP_TICKET_TTL_SECONDS", default=300)
# MediaMTX control API, used to reconcile channels stuck in `live`.
LIVE_MEDIAMTX_API = env("LIVE_MEDIAMTX_API", default="http://mediamtx:9997")
# Shared secret for the ready / notReady hooks. The auth hook cannot carry a
# header, so it relies on network isolation instead (nginx 404s the path).
LIVE_HOOK_SECRET = env("LIVE_HOOK_SECRET", default=SECRET_KEY[:32])
# Where MediaMTX writes recordings; shared volume with the Celery worker.
LIVE_RECORDINGS_DIR = Path(env("LIVE_RECORDINGS_DIR", default="/data/recordings"))
# Grace period before touching a recording — MediaMTX is still flushing when
# the notReady hook fires.
LIVE_RECORDING_SETTLE_SECONDS = env.int("LIVE_RECORDING_SETTLE_SECONDS", default=20)
LIVE_RECORDING_RETENTION_DAYS = env.int("LIVE_RECORDING_RETENTION_DAYS", default=7)
# Minimum gap between two chat messages from one socket. DRF throttles never
# see a WebSocket frame, so the consumer enforces this itself.
LIVE_CHAT_MIN_INTERVAL_SECONDS = env.float("LIVE_CHAT_MIN_INTERVAL_SECONDS", default=1.0)

# --------------------------------------------------------------------------
# Monetization (Phase 5)
# --------------------------------------------------------------------------
# The single switch between simulated and real payments. While it is on, the
# checkout UI shows a sandbox banner — a payment simulator that looks identical
# to a real one is how demo money becomes a support ticket.
PAYMENTS_USE_MOCK = env.bool("PAYMENTS_USE_MOCK", default=True)
# HMAC secret the mock provider signs its callbacks with, and the webhook
# verifier checks. A real provider supplies its own.
MOCK_PAYMENT_WEBHOOK_SECRET = env(
    "MOCK_PAYMENT_WEBHOOK_SECRET", default=SECRET_KEY[:40]
)
# How long the simulated payer takes to confirm on their handset.
MOCK_PAYMENT_CONFIRM_DELAY_SECONDS = env.int(
    "MOCK_PAYMENT_CONFIRM_DELAY_SECONDS", default=8
)
# Share of simulated payments that fail, so the failure path is exercised by the
# demo rather than only by a hand-written test.
MOCK_PAYMENT_FAILURE_PERCENT = env.int("MOCK_PAYMENT_FAILURE_PERCENT", default=15)
# A pending payment nobody confirmed is failed after this, or the user can never
# retry (the open-subscription constraint would block a second checkout).
PAYMENT_PENDING_TIMEOUT_MINUTES = env.int("PAYMENT_PENDING_TIMEOUT_MINUTES", default=30)
# How far ahead of period end renewals are attempted.
RENEWAL_LEAD_HOURS = env.int("RENEWAL_LEAD_HOURS", default=24)
# Where Celery reaches this API to deliver simulated webhooks — inside the
# compose network, so it never leaves the host.
INTERNAL_API_BASE_URL = env("INTERNAL_API_BASE_URL", default="http://backend:8000")

# Ads. First-party rotation only — no VAST, no exchange, no auction.
ADS_ENABLED = env.bool("ADS_ENABLED", default=True)
# Mid-roll on a 20-second clip is user-hostile.
ADS_MIN_DURATION_FOR_MIDROLL = env.int("ADS_MIN_DURATION_FOR_MIDROLL", default=120)

# --------------------------------------------------------------------------
# Shorts
#
# A video becomes a Short automatically when it is BOTH short enough and
# vertical enough. Derived at transcode time from ffprobe output, never set by
# the uploader — otherwise any video could declare itself a Short to get into
# the full-screen feed.
# --------------------------------------------------------------------------
SHORTS_MAX_DURATION_SECONDS = env.int("SHORTS_MAX_DURATION_SECONDS", default=90)
# Width / height. 1.0 admits square; anything wider is landscape and would be
# letterboxed in a portrait viewport.
SHORTS_MAX_ASPECT_RATIO = env.float("SHORTS_MAX_ASPECT_RATIO", default=1.0)

FFMPEG_BIN = env("FFMPEG_BIN", default="ffmpeg")
FFPROBE_BIN = env("FFPROBE_BIN", default="ffprobe")
HLS_SEGMENT_SECONDS = env.int("HLS_SEGMENT_SECONDS", default=4)
# Optional hardware encoder, e.g. "h264_nvenc" on an NVIDIA host. Default is the
# portable software encoder — see README "Performance".
FFMPEG_VIDEO_ENCODER = env("FFMPEG_VIDEO_ENCODER", default="libx264")
FFMPEG_PRESET = env("FFMPEG_PRESET", default="veryfast")

# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # Rejects suspended accounts on every request, not just at login.
        "apps.accounts.authentication.SuspensionAwareJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "upload": env("THROTTLE_UPLOAD", default="20/hour"),
        "auth": env("THROTTLE_AUTH", default="30/hour"),
        # Reserved for Phase 3+ so the rates live in one place.
        "comment": env("THROTTLE_COMMENT", default="60/hour"),
        "live_start": env("THROTTLE_LIVE_START", default="10/hour"),
        "checkout": env("THROTTLE_CHECKOUT", default="20/hour"),
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

DJOSER = {
    "LOGIN_FIELD": "email",
    "USER_CREATE_PASSWORD_RETYPE": True,
    "SEND_ACTIVATION_EMAIL": True,
    "SEND_CONFIRMATION_EMAIL": False,
    "ACTIVATION_URL": "activate/{uid}/{token}",
    "PASSWORD_RESET_CONFIRM_URL": "password/reset/{uid}/{token}",
    "PASSWORD_RESET_SHOW_EMAIL_NOT_FOUND": False,
    "SERIALIZERS": {
        "user": "apps.accounts.serializers.UserSerializer",
        "current_user": "apps.accounts.serializers.UserSerializer",
        "user_create_password_retype": "apps.accounts.serializers.UserCreateSerializer",
    },
    "EMAIL": {
        "activation": "apps.accounts.emails.ActivationEmail",
        "password_reset": "apps.accounts.emails.PasswordResetEmail",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "StreamVerse API",
    "DESCRIPTION": "Plateforme de partage video / Video sharing platform.",
    "VERSION": "0.2.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api",
    # Several models have a `status` field with different choice sets. Without
    # explicit names, spectacular invents collision-resolved ones like
    # "StatusAedEnum", which are meaningless in a generated client.
    "ENUM_NAME_OVERRIDES": {
        "VideoStatusEnum": "apps.videos.models.VideoStatus.choices",
        "ReportStatusEnum": "apps.engagement.models.ReportStatus.choices",
        "UploadStatusEnum": "apps.videos.models.UploadStatus.choices",
        "VisibilityEnum": "apps.videos.models.Visibility.choices",
        "ProcessingStageEnum": "apps.videos.models.ProcessingStage.choices",
        "ReportReasonEnum": "apps.engagement.models.ReportReason.choices",
        "LiveStatusEnum": "apps.live.models.LiveStatus.choices",
        "TransactionStatusEnum": "apps.monetization.models.TransactionStatus.choices",
        "SubscriptionStatusEnum": "apps.monetization.models.SubscriptionStatus.choices",
        "CampaignStatusEnum": "apps.monetization.models.CampaignStatus.choices",
        "PaymentProviderEnum": "apps.monetization.models.PaymentProvider.choices",
        "AdPlacementEnum": "apps.monetization.models.AdPlacement.choices",
        "SanctionTypeEnum": "apps.moderation.models.SanctionType.choices",
        "ModerationActionTypeEnum": "apps.moderation.models.ModerationActionType.choices",
    },
}

# --------------------------------------------------------------------------
# CORS / CSRF
# --------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
# tus-js-client reads these response headers; they must be explicitly exposed.
CORS_EXPOSE_HEADERS = [
    "Location", "Upload-Offset", "Upload-Length", "Upload-Expires",
    "Tus-Resumable", "Tus-Version", "Tus-Extension", "Tus-Max-Size",
]
CORS_ALLOW_HEADERS = [
    "accept", "authorization", "content-type", "origin", "x-requested-with",
    "tus-resumable", "upload-length", "upload-offset", "upload-metadata",
    "upload-defer-length", "upload-concat", "x-http-method-override",
]
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# --------------------------------------------------------------------------
# Redis / Channels / Celery
# --------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("CHANNEL_REDIS_URL", default="redis://redis:6379/1")]},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_REDIS_URL", default="redis://redis:6379/2"),
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/3")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=6 * 3600)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=6 * 3600 - 300)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # long transcode jobs must not be hoarded
CELERY_ACKS_LATE = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# --------------------------------------------------------------------------
# Email (Mailpit in dev)
# --------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@streamverse.local")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:8110")

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Public identity — used by sitemaps, robots.txt and link previews, which must
# emit absolute URLs and have no request to derive them from (a sitemap can be
# regenerated by a cron job with no HTTP context at all).
# --------------------------------------------------------------------------
SITE_URL = env("SITE_URL", default="http://localhost:8110").rstrip("/")
SITE_NAME = env("SITE_NAME", default="StreamVerse")
SITE_DESCRIPTION = env(
    "SITE_DESCRIPTION",
    default="Partagez, decouvrez et diffusez des videos en direct sur StreamVerse.",
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
if not DEBUG:
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
    # HSTS is opt-in because it is effectively irreversible for the duration of
    # max-age: a browser that has seen it refuses plain HTTP to this host even
    # if the certificate later lapses. Only enable it once TLS is permanent.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
        "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
    )
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"],
                               "propagate": False},
        "apps": {"level": env("LOG_LEVEL", default="INFO"), "handlers": ["console"],
                 "propagate": False},
    },
}

from config.jazzmin import JAZZMIN_SETTINGS, JAZZMIN_UI_TWEAKS  # noqa: E402,F401
