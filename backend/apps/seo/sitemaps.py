"""Sitemaps for the public catalogue.

Only genuinely public, indexable things appear here. Unlisted videos are
reachable by link but deliberately excluded — that is what "unlisted" means, and
listing them in a sitemap would hand them straight to a crawler.
"""
from django.contrib.sitemaps import Sitemap
from django.db.models import Max

from apps.accounts.models import User
from apps.catalog.models import Category
from apps.videos.models import Video


class _BaseSitemap(Sitemap):
    protocol = "https"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The demo runs on plain HTTP; emitting https:// URLs there would point
        # crawlers at a port that does not answer.
        from django.conf import settings

        self.protocol = "https" if settings.SITE_URL.startswith("https") else "http"


class VideoSitemap(_BaseSitemap):
    changefreq = "weekly"
    priority = 0.8
    limit = 5000

    def items(self):
        return (
            Video.objects.long_form()
            .order_by("-published_at")
            .only("id", "updated_at", "published_at")
        )

    def location(self, obj):
        return f"/watch/{obj.id}"

    def lastmod(self, obj):
        return obj.updated_at


class ShortSitemap(VideoSitemap):
    priority = 0.7

    def items(self):
        return (
            Video.objects.shorts()
            .order_by("-published_at")
            .only("id", "updated_at", "published_at")
        )

    def location(self, obj):
        return f"/shorts/{obj.id}"


class ChannelSitemap(_BaseSitemap):
    changefreq = "daily"
    priority = 0.6

    def items(self):
        # A channel with nothing public on it is an empty page; crawling it
        # spends budget for no result.
        return (
            User.objects.filter(is_active=True, videos__in=Video.objects.publicly_listed())
            .annotate(last_published=Max("videos__published_at"))
            .distinct()
            .order_by("username")
        )

    def location(self, obj):
        return f"/c/{obj.username}"

    def lastmod(self, obj):
        return obj.last_published


class CategorySitemap(_BaseSitemap):
    changefreq = "daily"
    priority = 0.5

    def items(self):
        return Category.objects.all().order_by("display_order", "name")

    def location(self, obj):
        return f"/browse?category={obj.slug}"


class StaticSitemap(_BaseSitemap):
    changefreq = "weekly"
    priority = 0.9

    def items(self):
        return ["/", "/browse", "/shorts", "/live", "/premium"]

    def location(self, item):
        return item


SITEMAPS = {
    "static": StaticSitemap,
    "videos": VideoSitemap,
    "shorts": ShortSitemap,
    "channels": ChannelSitemap,
    "categories": CategorySitemap,
}
