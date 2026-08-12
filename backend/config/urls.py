"""Root URLConf."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.core.views import HealthView

api_patterns = [
    # Djoser: signup, activation, password reset, /users/me/
    path("auth/", include("djoser.urls")),
    path("auth/", include("djoser.urls.jwt")),
    path("accounts/", include("apps.accounts.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("", include("apps.videos.urls")),
    path("", include("apps.engagement.urls")),
    path("", include("apps.search.urls")),
    path("", include("apps.live.urls")),
    path("", include("apps.monetization.urls")),
    path("", include("apps.moderation.urls")),
    path("", include("apps.library.urls")),
    path("health/", HealthView.as_view(), name="health"),
    # OpenAPI
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    # robots.txt, sitemap.xml and the crawler link-preview renderers.
    path("", include("apps.seo.urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.BASE_DIR / "media")
