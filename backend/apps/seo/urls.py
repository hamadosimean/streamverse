"""Crawler-facing routes.

These sit at the site root, not under /api/, because that is where robots.txt
and sitemap.xml must live to be found, and because the preview URLs have to
mirror the SPA paths a person would actually share.
"""
from django.contrib.sitemaps.views import sitemap
from django.urls import path

from apps.seo.sitemaps import SITEMAPS
from apps.seo.views import (
    channel_preview,
    robots_txt,
    site_preview,
    video_preview,
)

app_name = "seo"

urlpatterns = [
    path("robots.txt", robots_txt, name="robots"),
    # Deliberately NOT cached. An hour-old sitemap keeps advertising a video
    # that has since been taken down or made private, which is the one kind of
    # staleness that actually matters here — a takedown has to stop pointing
    # crawlers at the video immediately. The queries behind it are indexed and
    # column-limited, and a crawler fetches this rarely.
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS},
         name="django.contrib.sitemaps.views.sitemap"),

    # Server-rendered link previews. Nginx routes only known social crawlers
    # here; a human hitting these paths gets the SPA.
    path("_preview/site", site_preview, name="site-preview"),
    path("_preview/watch/<uuid:video_id>", video_preview, name="video-preview"),
    path("_preview/c/<str:username>", channel_preview, name="channel-preview"),
]
