"""Transcoding-progress fan-out over Channels.

The uploader's browser joins `upload_<video_id>`; every pipeline task publishes
here. Without this the frontend would have to poll, which for a 20-minute encode
means hundreds of pointless requests and a progress bar that lurches.

Weighting: the stages do not take equal time, so a naive "stage 3 of 5 = 60%"
bar would sit at 40% for ten minutes and then sprint. The weights below reflect
roughly where the wall-clock actually goes.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.videos.models import ProcessingStage, Video

logger = logging.getLogger(__name__)

# (stage, share of total wall clock)
STAGE_WEIGHTS: dict[str, tuple[float, float]] = {
    # stage: (start_fraction, end_fraction)
    ProcessingStage.QUEUED: (0.00, 0.02),
    ProcessingStage.PROBING: (0.02, 0.06),
    ProcessingStage.TRANSCODING: (0.06, 0.82),
    ProcessingStage.PACKAGING: (0.82, 0.86),
    ProcessingStage.THUMBNAILS: (0.86, 0.94),
    ProcessingStage.PUBLISHING: (0.94, 1.00),
    ProcessingStage.DONE: (1.00, 1.00),
}


def group_name(video_id) -> str:
    return f"upload_{video_id}"


def overall_percent(stage: str, stage_fraction: float = 0.0) -> int:
    start, end = STAGE_WEIGHTS.get(stage, (0.0, 1.0))
    stage_fraction = max(0.0, min(stage_fraction, 1.0))
    return int(round((start + (end - start) * stage_fraction) * 100))


def publish(video: Video, stage: str, stage_fraction: float = 0.0,
            detail: str = "", persist: bool = True) -> None:
    """Send a progress frame and (by default) persist it.

    Persisting matters for the reload case: a user who refreshes mid-encode gets
    the current percentage from the REST payload rather than a blank bar until
    the next WebSocket frame.
    """
    percent = overall_percent(stage, stage_fraction)

    if persist:
        Video.objects.filter(pk=video.pk).update(
            processing_stage=stage, processing_progress=percent
        )
        video.processing_stage = stage
        video.processing_progress = percent

    payload = {
        "type": "progress.update",
        "video_id": str(video.pk),
        "status": video.status,
        "stage": stage,
        "percent": percent,
        "detail": detail,
    }
    _send(video.pk, payload)


def publish_terminal(video: Video, detail: str = "") -> None:
    """Announce the final state (ready / failed) so the client can stop listening."""
    _send(
        video.pk,
        {
            "type": "progress.update",
            "video_id": str(video.pk),
            "status": video.status,
            "stage": video.processing_stage,
            "percent": video.processing_progress,
            "detail": detail or video.failure_reason,
            "terminal": True,
        },
    )


def _send(video_id, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover - only when CHANNEL_LAYERS is unset
        return
    try:
        async_to_sync(layer.group_send)(group_name(video_id), payload)
    except Exception:
        # A dropped progress frame must never fail the encode.
        logger.warning("Could not publish progress for video %s", video_id, exc_info=True)
