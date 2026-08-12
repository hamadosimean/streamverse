"""Live background work: recording -> VOD, and state reconciliation."""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.live.models import LiveChannel, LiveRecording, LiveStatus
from apps.videos.models import Video, VideoStatus, Visibility
from apps.videos.services import pipeline
from apps.videos.tasks import start_transcoding_pipeline

logger = logging.getLogger(__name__)


def recordings_dir(channel: LiveChannel) -> Path:
    """MediaMTX writes under `<root>/<path>/`, mirroring the RTMP path."""
    return Path(settings.LIVE_RECORDINGS_DIR) / channel.rtmp_path


def _session_files(session: LiveRecording) -> list[Path]:
    """Recording segments belonging to this session.

    Matched by mtime window rather than by filename: MediaMTX's `%f`
    timestamp format is configurable, and parsing it would couple this code to
    a config string someone will eventually change.
    """
    directory = recordings_dir(session.live_channel)
    if not directory.exists():
        return []

    start = session.started_at - timedelta(seconds=30)
    end = (session.ended_at or timezone.now()) + timedelta(
        seconds=settings.LIVE_RECORDING_SETTLE_SECONDS + 60
    )

    files = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in (".mp4", ".ts", ".mkv"):
            continue
        mtime = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.get_current_timezone()
        )
        if start <= mtime <= end and path.stat().st_size > 0:
            files.append(path)

    return sorted(files, key=lambda p: p.stat().st_mtime)


def _concatenate(files: list[Path], destination: Path) -> Path:
    """Join multiple recording segments into one file.

    Stream copy, no re-encode: the segments already share an encoder
    configuration, and re-encoding here would waste an hour of CPU on work the
    VOD pipeline is about to do properly anyway.
    """
    if len(files) == 1:
        shutil.copy2(files[0], destination)
        return destination

    listing = destination.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in files))

    result = subprocess.run(
        [settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(destination)],
        capture_output=True, text=True, timeout=3600,
    )
    listing.unlink(missing_ok=True)

    if result.returncode != 0 or not destination.exists():
        raise RuntimeError(
            f"Concatenation des segments echouee: {result.stderr[-600:]}"
        )
    return destination


@shared_task(name="live.convert_recording_to_vod", bind=True, max_retries=3)
def convert_recording_to_vod(self, session_id: int) -> dict:
    """Push a finished live recording through the **standard VOD pipeline**.

    Deliberately not a second, parallel transcoding path: the recording becomes
    an ordinary `Video` and goes through exactly the same probe → ladder →
    package → thumbnails → publish chain as a user upload. One pipeline to keep
    correct instead of two.

    The result is created **private**, so a stream that captured something the
    broadcaster did not intend is not republished automatically.
    """
    try:
        session = LiveRecording.objects.select_related(
            "live_channel", "live_channel__user"
        ).get(pk=session_id)
    except LiveRecording.DoesNotExist:
        return {"status": "missing_session"}

    if session.converted_video_id:
        return {"status": "already_converted",
                "video_id": str(session.converted_video_id)}

    channel = session.live_channel
    files = _session_files(session)

    if not files:
        # MediaMTX may still be flushing; retry a couple of times before
        # declaring the recording lost.
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30 * (self.request.retries + 1))
        session.conversion_error = (
            "Aucun fichier d'enregistrement trouve pour cette session. "
            "L'enregistrement etait-il active sur MediaMTX ?"
        )
        session.save(update_fields=["conversion_error", "updated_at"])
        logger.warning("live: no recording files for session %s", session_id)
        return {"status": "no_files"}

    total_bytes = sum(f.stat().st_size for f in files)
    started = timezone.localtime(session.started_at)

    video = Video.objects.create(
        uploader=channel.user,
        title=f"{channel.title or channel.slug} — {started:%d/%m/%Y %H:%M}",
        description=(
            f"Enregistrement du direct du {started:%d/%m/%Y a %H:%M}.\n"
            f"Duree: {session.duration_seconds // 60} min · "
            f"Pic de spectateurs: {session.peak_viewer_count}"
        ),
        status=VideoStatus.PROCESSING,
        visibility=Visibility.PRIVATE,
        category=channel.category,
        original_filename=f"live-{channel.slug}-{started:%Y%m%d-%H%M%S}.mp4",
        original_mime_type="video/mp4",
        original_size_bytes=total_bytes,
    )

    destination = pipeline.local_source_path(video)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        _concatenate(files, destination)
    except Exception as exc:
        session.conversion_error = str(exc)[:2000]
        session.save(update_fields=["conversion_error", "updated_at"])
        video.mark_failed(f"Preparation de l'enregistrement echouee: {exc}")
        logger.exception("live: concatenation failed for session %s", session_id)
        return {"status": "concat_failed"}

    session.converted_video = video
    session.recorded_file = str(files[0].parent)
    session.recorded_size_bytes = total_bytes
    session.conversion_error = ""
    session.save(update_fields=["converted_video", "recorded_file",
                                "recorded_size_bytes", "conversion_error",
                                "updated_at"])

    start_transcoding_pipeline.delay(str(video.pk))
    logger.info("live: session %s -> video %s (%d file(s), %.1f MiB)",
                session_id, video.pk, len(files), total_bytes / 1024 ** 2)

    return {"status": "queued", "video_id": str(video.pk), "files": len(files)}


@shared_task(name="live.reconcile_live_state")
def reconcile_live_state() -> dict:
    """Correct channels stuck in `live` after MediaMTX never fired its hook.

    The `runOnNotReady` hook is best-effort: if MediaMTX is killed, the hook
    never runs and the channel would advertise a stream nobody can watch.
    MediaMTX's own API is the source of truth for what is actually publishing.
    """
    marked_live = LiveChannel.objects.filter(status=LiveStatus.LIVE)
    if not marked_live.exists():
        return {"checked": 0, "ended": 0}

    try:
        response = requests.get(
            f"{settings.LIVE_MEDIAMTX_API}/v3/paths/list", timeout=5
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        # Cannot reach MediaMTX: do nothing rather than mass-ending live
        # channels because of a transient network blip.
        logger.warning("live: MediaMTX API unreachable, skipping reconcile (%s)", exc)
        return {"checked": 0, "ended": 0, "error": "api_unreachable"}

    publishing = {
        item.get("name")
        for item in payload.get("items", [])
        if item.get("ready")
    }

    from apps.live import services

    ended = 0
    for channel in marked_live.select_related("user"):
        if channel.rtmp_path not in publishing:
            logger.info("live: %s marked live but not publishing — closing session",
                        channel.slug)
            services.end_session(channel)
            ended += 1

    return {"checked": marked_live.count(), "ended": ended}


@shared_task(name="live.cleanup_old_recordings")
def cleanup_old_recordings(retain_days: int | None = None) -> dict:
    """Delete raw recording files once they are safely converted.

    The converted `Video` holds the durable copy in object storage; keeping the
    raw fMP4 as well doubles the storage cost of every stream.
    """
    retain_days = retain_days or settings.LIVE_RECORDING_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=retain_days)

    freed = 0
    removed = 0
    for session in LiveRecording.objects.filter(
        ended_at__lt=cutoff, converted_video__isnull=False
    ).select_related("live_channel"):
        for path in _session_files(session):
            try:
                freed += path.stat().st_size
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("live: could not remove %s", path)

    if removed:
        logger.info("live: removed %d recording file(s), %.1f MiB freed",
                    removed, freed / 1024 ** 2)
    return {"removed": removed, "bytes_freed": freed}
