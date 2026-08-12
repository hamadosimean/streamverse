"""A viewer's personal relationships: what they watched, saved, and who they follow.

Three models that look unrelated but share one shape — a row per (user, thing)
with a timestamp — and one audience: the signed-in viewer's own library. Keeping
them together means one app owns "my stuff" rather than scattering it across
videos, accounts and engagement.

**Watch history is deliberately separate from `engagement.View`.** They answer
different questions and have different lifetimes:

* `View` is *analytics*: deduplicated per 12-hour bucket, feeds `view_count`,
  pruned after 180 days, and anonymous viewers have rows too.
* `WatchHistoryEntry` is *the viewer's own record*: one row per video ever
  watched, updated in place, and **deletable by the user**.

Deriving history from `View` would mean clearing your history silently
decrements the creator's view count — a privacy action that quietly falsifies
someone else's stats.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class WatchHistoryEntry(models.Model):
    """One video the user has watched, with where they got to.

    `progress_seconds` is what makes "continue watching" possible; it is the
    furthest point reached, not the last position, so seeking backwards near the
    end does not lose the fact that they nearly finished.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="watch_history")
    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE,
                              related_name="history_entries")

    progress_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False, db_index=True)
    watch_count = models.PositiveIntegerField(default=1)

    first_watched_at = models.DateTimeField(default=timezone.now)
    last_watched_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = _("entree d'historique")
        verbose_name_plural = _("historique de visionnage")
        ordering = ("-last_watched_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "video"),
                                    name="uniq_history_per_user_video"),
        ]
        indexes = [models.Index(fields=["user", "-last_watched_at"])]

    def __str__(self):
        return f"{self.user_id} watched {self.video_id}"

    @property
    def progress_percent(self) -> int:
        if not self.video.duration_seconds:
            return 0
        return min(100, int(self.progress_seconds * 100 / self.video.duration_seconds))

    @property
    def is_resumable(self) -> bool:
        """Worth offering "continue watching"?

        Not if they barely started, and not if they essentially finished —
        offering to resume a video at 98% is noise.
        """
        percent = self.progress_percent
        return 5 <= percent <= 95 and not self.completed


class Bookmark(TimeStampedModel):
    """Saved for later. One row per (user, video)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="bookmarks")
    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE,
                              related_name="bookmarks")
    note = models.CharField(
        max_length=200, blank=True,
        help_text=_("Note personnelle facultative, visible du seul auteur."),
    )

    class Meta:
        verbose_name = _("favori")
        verbose_name_plural = _("favoris")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "video"),
                                    name="uniq_bookmark_per_user_video"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.user_id} saved {self.video_id}"


class Follow(TimeStampedModel):
    """A follow edge between two users.

    Note on scope: v1 was specified as follow-less browsing, and this was added
    later at the product owner's request. It is a plain social graph — a follow
    affects the follower's own feed and nothing else. There are still **no
    notifications**: nobody is emailed or pushed when a channel uploads, which
    was the part of "no follow graph" that carried the real cost.
    """

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following"
    )
    channel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followers",
        help_text=_("L'utilisateur suivi (sa chaine)."),
    )

    class Meta:
        verbose_name = _("abonnement a une chaine")
        verbose_name_plural = _("abonnements aux chaines")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("follower", "channel"),
                                    name="uniq_follow_per_pair"),
            # Following yourself would put your own uploads in your "new from
            # channels you follow" feed, which is noise, not a feature.
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("channel")),
                name="no_self_follow",
            ),
        ]
        indexes = [
            models.Index(fields=["follower", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.follower_id} -> {self.channel_id}"
