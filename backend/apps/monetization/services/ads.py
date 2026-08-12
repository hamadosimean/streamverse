"""First-party ad selection.

**This is not a programmatic ad system.** There is no VAST/VPAID document, no ad
exchange, no header bidding, no auction and no third-party tracking. It picks one
of *our own* campaign rows by weighted rotation and tells the player to show it.
Real ad-network integration is a substantial separate project; the README says
so plainly rather than implying equivalence.

The one rule that must never be got wrong: **an ad-free subscriber sees no ads.**
That check happens here, server-side, at selection time — not in the player,
which a user controls.
"""
from __future__ import annotations

import logging
import random

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.monetization.models import (
    AdCampaign,
    AdImpression,
    AdPlacement,
    UserSubscription,
)

logger = logging.getLogger(__name__)


def viewer_is_ad_free(user) -> bool:
    """Does this viewer hold a subscription that removes ads?

    Anonymous viewers never are. Checked against `active()`, which requires both
    an `active` status *and* an unexpired period — a lapsed row that the renewal
    task has not swept yet must not keep granting benefits.
    """
    if user is None or not user.is_authenticated:
        return False
    return UserSubscription.objects.active().filter(
        user=user, plan__ad_free=True
    ).exists()


def eligible_campaigns(video=None, placement: str | None = None):
    """Campaigns that may serve against this video right now."""
    queryset = AdCampaign.objects.eligible()

    if placement:
        queryset = queryset.filter(placement=placement)

    if video is not None:
        # A campaign with no categories targets everything; one with categories
        # only serves against those. Expressed as a single Q so it stays one
        # query rather than an OR of two querysets.
        untargeted = Q(categories__isnull=True)
        if video.category_id:
            queryset = queryset.filter(untargeted | Q(categories__id=video.category_id))
        else:
            queryset = queryset.filter(untargeted)

    return queryset.distinct()


def _weighted_choice(campaigns: list[AdCampaign]) -> AdCampaign | None:
    """Pick one campaign, honouring `weight`.

    Weighted rotation rather than "highest bidder": there is no auction here, and
    pretending otherwise would be dressing up a round-robin as an ad exchange.
    """
    if not campaigns:
        return None
    total = sum(max(c.weight, 1) for c in campaigns)
    cursor = random.uniform(0, total)
    upto = 0.0
    for campaign in campaigns:
        upto += max(campaign.weight, 1)
        if upto >= cursor:
            return campaign
    return campaigns[-1]


def select_ads_for_playback(*, video, user, session_key: str = "") -> dict:
    """Decide what, if anything, plays around this video.

    Returns a plan the player can follow: a pre-roll, a mid-roll with a cue
    point, both, or nothing at all.
    """
    if not settings.ADS_ENABLED:
        return {"ads_enabled": False, "reason": "ads_disabled", "breaks": []}

    if viewer_is_ad_free(user):
        # The honest answer, and the client shows "ad-free" because of it.
        return {"ads_enabled": False, "reason": "subscriber_ad_free", "breaks": []}

    breaks = []
    for placement in (AdPlacement.PRE_ROLL, AdPlacement.MID_ROLL):
        # Mid-roll on a 20-second clip is user-hostile; skip it on short videos.
        if (placement == AdPlacement.MID_ROLL
                and video.duration_seconds < settings.ADS_MIN_DURATION_FOR_MIDROLL):
            continue

        candidates = list(eligible_campaigns(video=video, placement=placement))
        campaign = _weighted_choice(candidates)
        if campaign is None:
            continue

        impression = _open_impression(campaign, video, user, session_key, placement)

        cue = (0 if placement == AdPlacement.PRE_ROLL
               else int(video.duration_seconds * campaign.mid_roll_position))

        breaks.append({
            "impression_id": str(impression.pk),
            "campaign_id": campaign.pk,
            "placement": placement,
            "cue_seconds": cue,
            "advertiser_name": campaign.advertiser_name,
            "title": campaign.title,
            "creative_url": campaign.creative.url if campaign.creative else None,
            "creative_is_video": campaign.creative_is_video,
            "click_url": campaign.click_url,
            "duration_seconds": campaign.duration_seconds,
            "skippable_after_seconds": campaign.skippable_after_seconds,
        })

    return {
        "ads_enabled": bool(breaks),
        "reason": "ok" if breaks else "no_eligible_campaign",
        "breaks": breaks,
        # Said out loud in the payload so nobody mistakes this for programmatic.
        "delivery": "first_party_rotation",
    }


def _open_impression(campaign, video, user, session_key, placement) -> AdImpression:
    """Record the impression and bump the cap counter at selection time.

    Counted on serve, not on completion: an impression that was delivered and
    then abandoned still consumed inventory, and counting only completions would
    let a campaign blow far past its cap.
    """
    with db_transaction.atomic():
        impression = AdImpression.objects.create(
            campaign=campaign,
            video=video,
            viewer=user if (user and user.is_authenticated) else None,
            session_key=session_key[:64],
            placement=placement,
        )
        AdCampaign.objects.filter(pk=campaign.pk).update(
            impression_count=F("impression_count") + 1
        )
    return impression


def record_impression_progress(*, impression_id, watched_seconds: int,
                               completed: bool = False, skipped: bool = False,
                               clicked: bool = False) -> AdImpression | None:
    """Update an impression as the ad plays out."""
    impression = AdImpression.objects.filter(pk=impression_id).select_related(
        "campaign"
    ).first()
    if impression is None:
        return None

    became_complete = completed and not impression.completed
    became_clicked = clicked and not impression.clicked

    impression.watched_seconds = max(impression.watched_seconds, watched_seconds)
    impression.completed = impression.completed or completed
    impression.skipped = impression.skipped or skipped
    impression.clicked = impression.clicked or clicked
    impression.save(update_fields=["watched_seconds", "completed", "skipped",
                                   "clicked"])

    updates = {}
    if became_complete:
        updates["completed_count"] = F("completed_count") + 1
    if became_clicked:
        updates["click_count"] = F("click_count") + 1
    if updates:
        AdCampaign.objects.filter(pk=impression.campaign_id).update(**updates)

    return impression


def expire_finished_campaigns() -> int:
    """Move campaigns past their end date or cap to `ended`.

    Selection already filters them out; this makes the state visible in the admin
    instead of leaving a campaign that looks active but never serves.
    """
    from apps.monetization.models import CampaignStatus

    now = timezone.now()
    ended = AdCampaign.objects.filter(
        status=CampaignStatus.ACTIVE, end_date__lt=now
    ).update(status=CampaignStatus.ENDED)

    capped = 0
    for campaign in AdCampaign.objects.filter(
        status=CampaignStatus.ACTIVE, impression_cap__gt=0
    ).only("pk", "impression_cap", "impression_count"):
        if campaign.impression_count >= campaign.impression_cap:
            AdCampaign.objects.filter(pk=campaign.pk).update(
                status=CampaignStatus.ENDED
            )
            capped += 1

    if ended or capped:
        logger.info("ads: %d campaign(s) ended by date, %d by cap", ended, capped)
    return ended + capped
