"""Library write paths."""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.library.models import Bookmark, Follow, WatchHistoryEntry

logger = logging.getLogger(__name__)

# Below this, a "view" was a misclick and does not belong in someone's history.
MIN_HISTORY_SECONDS = 3
# Past this share of the runtime, treat the video as finished.
COMPLETION_THRESHOLD = 0.95


def record_watch(*, user, video, progress_seconds: int) -> WatchHistoryEntry | None:
    """Upsert a history entry as the viewer watches.

    Called from the view-ping path, so it runs several times per playback; it is
    written to be idempotent and cheap. Anonymous viewers get nothing — history
    is a signed-in feature by definition.
    """
    if user is None or not user.is_authenticated:
        return None
    if progress_seconds < MIN_HISTORY_SECONDS:
        return None

    now = timezone.now()
    entry, created = WatchHistoryEntry.objects.get_or_create(
        user=user, video=video,
        defaults={"progress_seconds": progress_seconds,
                  "first_watched_at": now, "last_watched_at": now},
    )

    if created:
        return entry

    updates = {"last_watched_at": now}

    # Furthest point reached, not last position: seeking back near the end must
    # not lose the fact that they nearly finished.
    if progress_seconds > entry.progress_seconds:
        updates["progress_seconds"] = progress_seconds

    if (video.duration_seconds
            and progress_seconds >= video.duration_seconds * COMPLETION_THRESHOLD):
        updates["completed"] = True

    # A rewatch is a new session, not a continuation: the viewer came back after
    # the video had been away from the top of their history.
    if (now - entry.last_watched_at).total_seconds() > 6 * 3600:
        updates["watch_count"] = F("watch_count") + 1

    WatchHistoryEntry.objects.filter(pk=entry.pk).update(**updates)
    return entry


def toggle_bookmark(*, user, video, note: str = "") -> tuple[bool, Bookmark | None]:
    """Save or unsave. Returns `(is_bookmarked, row)`."""
    existing = Bookmark.objects.filter(user=user, video=video).first()
    if existing is not None:
        existing.delete()
        return False, None

    try:
        bookmark = Bookmark.objects.create(user=user, video=video,
                                           note=note.strip()[:200])
    except IntegrityError:
        # Double-clicked; the row the race created is the answer.
        return True, Bookmark.objects.get(user=user, video=video)
    return True, bookmark


@transaction.atomic
def toggle_follow(*, follower, channel) -> tuple[bool, int]:
    """Follow or unfollow a channel. Returns `(is_following, follower_count)`.

    Counters live on `User` and are recomputed from the rows inside this
    transaction rather than incremented — cheap (the index covers it) and immune
    to the drift an increment/decrement pair accumulates.
    """
    if follower.pk == channel.pk:
        raise ValueError("Vous ne pouvez pas vous abonner a votre propre chaine.")

    existing = Follow.objects.filter(follower=follower, channel=channel).first()
    if existing is not None:
        existing.delete()
        is_following = False
    else:
        try:
            Follow.objects.create(follower=follower, channel=channel)
        except IntegrityError:
            pass
        is_following = True

    count = Follow.objects.filter(channel=channel).count()
    type(channel).objects.filter(pk=channel.pk).update(follower_count=count)
    type(follower).objects.filter(pk=follower.pk).update(
        following_count=Follow.objects.filter(follower=follower).count()
    )

    return is_following, count


def followed_channel_ids(user) -> list[int]:
    if user is None or not user.is_authenticated:
        return []
    return list(Follow.objects.filter(follower=user).values_list("channel_id",
                                                                flat=True))


def annotate_viewer_state(videos, user):
    """Attach `is_bookmarked` / `my_reaction` to a page of videos in two queries.

    Doing this per-video in the serializer would be two queries per card — 48 on
    a 24-item grid. The maps are built once and read from memory.
    """
    if user is None or not user.is_authenticated:
        return {}, {}

    ids = [v.pk for v in videos]
    if not ids:
        return {}, {}

    from apps.engagement.models import Like

    bookmarked = set(
        Bookmark.objects.filter(user=user, video_id__in=ids)
        .values_list("video_id", flat=True)
    )
    reactions = dict(
        Like.objects.filter(user=user, video_id__in=ids)
        .values_list("video_id", "is_like")
    )
    return bookmarked, reactions
