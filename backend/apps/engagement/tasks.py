"""Engagement background work.

The denormalised counters on `Video` are a cache. They are written
transactionally on every mutation, but a crash between the row write and the
counter update would leave them slightly off — so they are reconciled against
the source tables on a schedule rather than trusted forever.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from apps.engagement.models import Comment, Like, View
from apps.videos.models import Video, VideoStatus

logger = logging.getLogger(__name__)


@shared_task(name="engagement.reconcile_counters")
def reconcile_counters(limit: int = 5000) -> dict:
    """Recompute view/like/dislike/comment counts from the source rows.

    Only writes rows that actually drifted, so a healthy database does zero
    writes and the task stays cheap enough to run hourly.
    """
    videos = (
        Video.objects.annotate(
            real_views=Count("views", filter=Q(views__counted=True), distinct=True),
            real_likes=Count("likes", filter=Q(likes__is_like=True), distinct=True),
            real_dislikes=Count("likes", filter=Q(likes__is_like=False), distinct=True),
            real_comments=Count("comments", filter=Q(comments__is_deleted=False),
                                distinct=True),
        )
        .order_by("-uploaded_at")[:limit]
    )

    corrected = 0
    for video in videos:
        changes = {}
        if video.view_count != video.real_views:
            changes["view_count"] = video.real_views
        if video.like_count != video.real_likes:
            changes["like_count"] = video.real_likes
        if video.dislike_count != video.real_dislikes:
            changes["dislike_count"] = video.real_dislikes
        if video.comment_count != video.real_comments:
            changes["comment_count"] = video.real_comments

        if changes:
            Video.objects.filter(pk=video.pk).update(**changes)
            corrected += 1
            logger.info("counter drift corrected on %s: %s", video.pk, changes)

    return {"scanned": len(videos), "corrected": corrected}


@shared_task(name="engagement.prune_view_rows")
def prune_view_rows(retain_days: int = 180) -> dict:
    """Drop old raw `View` rows.

    The aggregate lives on `Video.view_count`; the individual rows exist for
    deduplication and analytics, and both lose their value quickly. Keeping them
    forever would make this the largest table in the database by an order of
    magnitude.
    """
    cutoff = timezone.now() - timedelta(days=retain_days)
    deleted, _ = View.objects.filter(created_at__lt=cutoff).delete()
    if deleted:
        logger.info("pruned %d view rows older than %d days", deleted, retain_days)
    return {"deleted": deleted}


@shared_task(name="engagement.refresh_trending_cache")
def refresh_trending_cache() -> dict:
    """Pre-aggregate the trending feed into Redis.

    The homepage is the most requested page on the site and its trending list is
    identical for every visitor, so computing it per request is pure waste.
    """
    since = timezone.now() - timedelta(days=30)

    trending = list(
        Video.objects.publicly_listed()
        .filter(published_at__gte=since)
        .order_by("-view_count", "-published_at")
        .values_list("id", flat=True)[:24]
    )
    most_viewed = list(
        Video.objects.publicly_listed()
        .order_by("-view_count")
        .values_list("id", flat=True)[:24]
    )

    cache.set("feed:trending", [str(pk) for pk in trending], 600)
    cache.set("feed:most_viewed", [str(pk) for pk in most_viewed], 600)

    return {"trending": len(trending), "most_viewed": len(most_viewed)}


@shared_task(name="engagement.rebuild_search_index")
def rebuild_search_index(only_stale: bool = True) -> dict:
    """Refresh the PostgreSQL full-text vectors.

    Metadata edits update a video's vector inline, so this is a safety net for
    rows that changed through a path that did not (admin edits, data migrations,
    a tag renamed underneath them).
    """
    from apps.search.services import update_search_vector

    queryset = Video.objects.filter(status=VideoStatus.READY)
    if only_stale:
        queryset = queryset.filter(search_vector__isnull=True)

    indexed = 0
    for video in queryset.prefetch_related("tags").iterator(chunk_size=200):
        update_search_vector(video)
        indexed += 1

    if indexed:
        logger.info("search vectors rebuilt for %d videos", indexed)
    return {"indexed": indexed}
