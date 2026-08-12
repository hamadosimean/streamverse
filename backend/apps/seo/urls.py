"""Crawler-facing routes.

These sit at the site root, not under /api/, because that is where robots.txt
and sitemap.xml must live to be found, and because the preview URLs have to
mirror the SPA paths a person would actually share.
"""
from django.contrib.sitemaps.views import sitemap
from django.urls import path
from django.views.decorators.cache import cache_page

from apps.seo.sitemaps import SITEMAPS
from apps.seo.views import channel_preview, robots_txt, video_preview

app_name = "seo"

urlpatterns = [
    path("robots.txt", robots_txt, name="robots"),
    # A full sitemap walks the whole public catalogue; a crawler may request it
    # repeatedly, so it is cached rather than regenerated per hit.
    path("sitemap.xml", cache_page(60 * 60)(sitemap), {"sitemaps": SITEMAPS},
         name="django.contrib.sitemaps.views.sitemap"),

    # Server-rendered link previews. Nginx routes only known social crawlers
    # here; a human hitting these paths gets the SPA.
    path("_preview/watch/<uuid:video_id>", video_preview, name="video-preview"),
    path("_preview/c/<str:username>", channel_preview, name="channel-preview"),
]
