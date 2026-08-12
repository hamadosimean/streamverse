"""Crawler-facing views: robots.txt and server-rendered link previews.

Why this exists: StreamVerse is a single-page app, so the HTML served for
/watch/<id> is an empty shell. Google executes JavaScript and will eventually
see the rendered page, but the crawlers behind link unfurling — Facebook,
Slack, WhatsApp, Discord, LinkedIn — do not run scripts at all. Without this,
every shared video link previews as the generic site title.

These views render the *same* title, description and poster the user sees, so
this is a rendering accommodation, not cloaking.
"""
import json

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe
from django.utils.translation import get_language, gettext as _
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from apps.accounts.models import User
from apps.videos.models import Video, Visibility


def _one_line(text: str, limit: int = 300) -> str:
    """Collapse a description into meta-tag shape.

    Newlines are legal inside an attribute but several unfurlers render them
    literally or truncate at the first one, so the paragraph breaks a video
    description legitimately contains are flattened here.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    # Cut on a word boundary rather than mid-word.
    return collapsed[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "\u2026"


def _absolute(path: str) -> str:
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def _jsonld(payload: dict) -> str:
    """Serialise a JSON-LD block safely for embedding in HTML.

    Django's template engine escapes for HTML, not JSON — a title containing a
    quote would produce a document that no parser accepts. Serialising here and
    escaping only the three characters that can break out of a <script> element
    is both correct JSON and safe HTML.
    """
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return mark_safe(f'<script type="application/ld+json">{raw}</script>')


def _poster(video: Video) -> str | None:
    # Preview cards are fetched by a third-party crawler with no credentials, so
    # a presigned private URL is useless to it (and would expire). Only public
    # posters are advertised.
    from apps.core import storage

    if not video.poster_path or video.visibility != Visibility.PUBLIC:
        return None
    return storage.public_url(video.poster_path, bucket=settings.MINIO_PUBLIC_BUCKET)


@require_GET
def robots_txt(request):
    """Keep crawlers out of the API, the admin and every signed-in surface.

    Those paths return either JSON, a login redirect or personal data; indexing
    them wastes crawl budget on pages that can never rank.
    """
    lines = [
        "User-agent: *",
        "Allow: /$",
        "Allow: /browse",
        "Allow: /shorts",
        "Allow: /live",
        "Allow: /premium",
        "Allow: /watch/",
        "Allow: /c/",
        "Disallow: /api/",
        "Disallow: /admin/",
        "Disallow: /manage/",
        "Disallow: /account",
        "Disallow: /studio",
        "Disallow: /upload",
        "Disallow: /library",
        "Disallow: /subscriptions",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /password/",
        "Disallow: /activate/",
        # A search-results page per query is infinite crawl space with no
        # independent value.
        "Disallow: /search",
        "",
        f"Sitemap: {_absolute('/sitemap.xml')}",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


@require_GET
@cache_control(public=True, max_age=300)
def video_preview(request, video_id):
    """Link-preview HTML for /watch/<id> and /shorts/<id>."""
    video = get_object_or_404(
        Video.objects.select_related("uploader", "category"), pk=video_id
    )
    # Private videos have no shareable preview; unlisted ones do, because the
    # person pasting the link already holds it.
    if not video.is_public_asset or not video.is_playable:
        raise Http404

    description = (video.description or "").strip()
    if not description:
        description = _("Regardez « %(title)s » sur %(site)s.") % {
            "title": video.title,
            "site": settings.SITE_NAME,
        }

    canonical = _absolute(
        f"/shorts/{video.id}" if video.is_short else f"/watch/{video.id}"
    )

    poster = _poster(video)
    description = _one_line(description)
    channel_url = _absolute(f"/c/{video.uploader.username}")
    author = video.uploader.display_name or video.uploader.username

    # VideoObject is what earns a video-rich result. uploadDate and thumbnailUrl
    # are the two properties Google treats as required.
    payload = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": video.title,
        "description": description,
        "uploadDate": video.published_at.isoformat() if video.published_at else None,
        "duration": f"PT{video.duration_seconds}S",
        "url": canonical,
        "interactionStatistic": {
            "@type": "InteractionCounter",
            "interactionType": "https://schema.org/WatchAction",
            "userInteractionCount": video.view_count,
        },
        "author": {"@type": "Person", "name": author, "url": channel_url},
        "publisher": {"@type": "Organization", "name": settings.SITE_NAME},
    }
    if poster:
        payload["thumbnailUrl"] = [poster]
    payload = {k: v for k, v in payload.items() if v is not None}

    return TemplateResponse(
        request,
        "seo/video_preview.html",
        {
            "video": video,
            "site_name": settings.SITE_NAME,
            "canonical": canonical,
            "poster": poster,
            "description": description,
            "channel_url": channel_url,
            "jsonld": _jsonld(payload),
            "language": get_language() or "fr",
            "noindex": video.visibility != Visibility.PUBLIC,
        },
    )


@require_GET
@cache_control(public=True, max_age=300)
def channel_preview(request, username):
    """Link-preview HTML for /c/<username>."""
    user = get_object_or_404(User, username=username.lower(), is_active=True)
    description = (user.bio or "").strip() or _(
        "La chaine de %(name)s sur %(site)s."
    ) % {"name": user.display_name or user.username, "site": settings.SITE_NAME}

    description = _one_line(description)
    canonical = _absolute(f"/c/{user.username}")
    name = user.display_name or user.username

    payload = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "url": canonical,
        "mainEntity": {
            "@type": "Person",
            "name": name,
            "alternateName": user.username,
            "description": description,
            "url": canonical,
            "interactionStatistic": {
                "@type": "InteractionCounter",
                "interactionType": "https://schema.org/FollowAction",
                "userInteractionCount": getattr(user, "follower_count", 0) or 0,
            },
        },
    }

    return TemplateResponse(
        request,
        "seo/channel_preview.html",
        {
            "channel": user,
            "site_name": settings.SITE_NAME,
            "canonical": canonical,
            "description": description,
            "jsonld": _jsonld(payload),
            "language": get_language() or "fr",
            "noindex": False,
        },
    )
