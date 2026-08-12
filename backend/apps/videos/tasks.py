"""The transcoding pipeline.

Shape (Section 5): a Celery **chain**, one task per stage, each taking and
returning the video id. Any stage raising drops the whole chain into
`on_pipeline_failure`, which sets `status=failed` with the real reason and leaves
a retry path. There is no state in which a video is `ready` with a missing
rendition.

Nothing here runs inline in a request — the web process only ever calls
`start_transcoding_pipeline.delay(...)`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from celery import chain, shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import storage
from apps.videos.models import (
    ProcessingStage,
    UploadSession,
    UploadStatus,
    Video,
    VideoRendition,
    VideoStatus,
    VideoThumbnail,
)
from apps.videos.services import ffmpeg, packaging, pipeline, progress
from apps.videos.services.ladder import Rendition, build_ladder

logger = logging.getLogger(__name__)


def _load(video_id) -> Video:
    return Video.objects.select_related("uploader").get(pk=video_id)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.start_pipeline")
def start_transcoding_pipeline(video_id: str) -> str:
    """Queue the full chain for one video."""
    video = _load(video_id)
    Video.objects.filter(pk=video.pk).update(
        status=VideoStatus.PROCESSING,
        processing_stage=ProcessingStage.QUEUED,
        processing_progress=0,
        failure_reason="",
        transcode_attempts=video.transcode_attempts + 1,
    )
    video.refresh_from_db()
    progress.publish(video, ProcessingStage.QUEUED, 1.0, "En file d'attente")

    workflow = chain(
        probe_source.s(str(video.pk)),
        transcode_renditions.s(),
        build_master_playlist.s(),
        generate_thumbnails.s(),
        finalize_video.s(),
    )
    workflow.on_error(on_pipeline_failure.s(str(video.pk)))
    workflow.apply_async()
    return str(video.pk)


# --------------------------------------------------------------------------
# Stage 1 — probe
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.probe_source")
def probe_source(video_id: str) -> str:
    video = _load(video_id)
    progress.publish(video, ProcessingStage.PROBING, 0.0, "Analyse du fichier source")

    source = pipeline.ensure_local_source(video)
    result = ffmpeg.probe(source)

    # Archive the original before we touch anything else, so a retry never
    # depends on the scratch volume still holding the file.
    original_key = pipeline.archive_original(video, Path(source))

    Video.objects.filter(pk=video.pk).update(
        duration_seconds=int(round(result.duration_seconds)),
        source_width=result.width,
        source_height=result.height,
        source_resolution=result.resolution,
        source_video_codec=result.video_codec,
        source_audio_codec=result.audio_codec,
        has_audio=result.has_audio,
        original_key=original_key,
    )
    video.refresh_from_db()

    # Classified here, immediately after probing: this is the first moment the
    # real duration and dimensions are known, and both are needed.
    Video.objects.filter(pk=video.pk).update(is_short=video.qualifies_as_short())
    video.refresh_from_db()
    progress.publish(
        video, ProcessingStage.PROBING, 1.0,
        f"{result.resolution} - {int(result.duration_seconds)} s",
    )
    return str(video.pk)


# --------------------------------------------------------------------------
# Stage 2 — transcode every rung
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.transcode_renditions")
def transcode_renditions(video_id: str) -> str:
    video = _load(video_id)
    source = pipeline.ensure_local_source(video)
    work = pipeline.work_dir(video)

    ladder = build_ladder(video.source_width, video.source_height)
    logger.info("video %s ladder: %s", video.pk,
                ", ".join(f"{r.label}({r.width}x{r.height})" for r in ladder))

    # A retry must not leave stale renditions from the failed attempt.
    video.renditions.all().delete()
    pipeline.purge_derived_assets(video)

    total = len(ladder)
    bucket = video.target_bucket

    for index, rendition in enumerate(ladder):
        out_dir = work / "hls" / rendition.label

        def publish(fraction: float, _index=index, _rendition=rendition):
            overall = (_index + fraction) / total
            progress.publish(
                video, ProcessingStage.TRANSCODING, overall,
                f"{_rendition.label} ({_index + 1}/{total})",
            )

        throttled = pipeline.ThrottledProgress(publish)
        throttled(0.0, force=True)

        stats = ffmpeg.transcode_rendition(
            source=source,
            out_dir=out_dir,
            rendition=rendition,
            duration_seconds=video.duration_seconds,
            has_audio=video.has_audio,
            progress_cb=throttled,
        )

        prefix = f"{video.asset_prefix}/hls/{rendition.label}"
        storage.upload_directory(out_dir, bucket, prefix)

        VideoRendition.objects.create(
            video=video,
            label=rendition.label,
            width=rendition.width,
            height=rendition.height,
            video_bitrate_kbps=rendition.video_bitrate_kbps,
            audio_bitrate_kbps=rendition.audio_bitrate_kbps,
            hls_playlist_path=f"{prefix}/{stats['playlist']}",
            file_size=stats["bytes"],
            segment_count=stats["segments"],
            codecs=rendition.codecs,
        )
        throttled(1.0, force=True)

    Video.objects.filter(pk=video.pk).update(storage_bucket=bucket)
    return str(video.pk)


# --------------------------------------------------------------------------
# Stage 3 — master playlist
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.build_master_playlist")
def build_master_playlist(video_id: str) -> str:
    video = _load(video_id)
    progress.publish(video, ProcessingStage.PACKAGING, 0.0, "Assemblage du manifeste")

    renditions = list(video.renditions.order_by("height"))
    if not renditions:
        raise RuntimeError("Aucun rendu disponible pour construire le manifeste.")

    entries: list[tuple[Rendition, str]] = []
    for row in renditions:
        entries.append(
            (
                Rendition(
                    label=row.label,
                    width=row.width,
                    height=row.height,
                    video_bitrate_kbps=row.video_bitrate_kbps,
                    audio_bitrate_kbps=row.audio_bitrate_kbps,
                    codecs=row.codecs,
                ),
                f"{row.label}/index.m3u8",
            )
        )

    master_text = packaging.build_master_playlist(entries)
    master_key = f"{video.asset_prefix}/hls/master.m3u8"
    storage.upload_bytes(
        master_text.encode("utf-8"),
        video.storage_bucket or video.target_bucket,
        master_key,
        content_type="application/vnd.apple.mpegurl",
    )

    Video.objects.filter(pk=video.pk).update(hls_master_path=master_key)
    video.refresh_from_db()
    progress.publish(video, ProcessingStage.PACKAGING, 1.0,
                     f"{len(renditions)} rendus disponibles")
    return str(video.pk)


# --------------------------------------------------------------------------
# Stage 4 — poster + scrubbing previews
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.generate_thumbnails")
def generate_thumbnails(video_id: str) -> str:
    video = _load(video_id)
    progress.publish(video, ProcessingStage.THUMBNAILS, 0.0, "Generation des miniatures")

    source = pipeline.ensure_local_source(video)
    work = pipeline.work_dir(video) / "thumbs"
    work.mkdir(parents=True, exist_ok=True)
    bucket = video.storage_bucket or video.target_bucket
    prefix = f"{video.asset_prefix}/thumbs"

    video.thumbnails.all().delete()

    # Poster: 10% in, which skips fade-ins and black leader frames.
    poster_at = max(min(video.duration_seconds * 0.1, video.duration_seconds - 0.1), 0)
    poster_file = work / "poster.jpg"
    ffmpeg.extract_poster(source, poster_file, poster_at)
    storage.upload_file(poster_file, bucket, f"{prefix}/poster.jpg")
    progress.publish(video, ProcessingStage.THUMBNAILS, 0.4, "Poster genere")

    VideoThumbnail.objects.create(
        video=video, timestamp_offset=poster_at,
        image_path=f"{prefix}/poster.jpg", is_poster=True,
    )

    # Scrubbing previews as one sprite sheet.
    sprite_file = work / "sprite.jpg"
    geometry = ffmpeg.build_sprite_sheet(source, sprite_file, video.duration_seconds)
    storage.upload_file(sprite_file, bucket, f"{prefix}/sprite.jpg")
    progress.publish(video, ProcessingStage.THUMBNAILS, 0.8, "Planche de miniatures")

    vtt_text = packaging.build_thumbnail_vtt("sprite.jpg", geometry,
                                             video.duration_seconds)
    storage.upload_bytes(vtt_text.encode("utf-8"), bucket,
                         f"{prefix}/thumbnails.vtt", content_type="text/vtt")

    VideoThumbnail.objects.bulk_create(
        [
            VideoThumbnail(
                video=video,
                timestamp_offset=timestamp,
                image_path=f"{prefix}/sprite.jpg",
                is_poster=False,
                sprite_x=x, sprite_y=y, sprite_width=w, sprite_height=h,
            )
            for timestamp, x, y, w, h in packaging.sprite_tile_positions(
                geometry, video.duration_seconds
            )
        ]
    )

    Video.objects.filter(pk=video.pk).update(
        poster_path=f"{prefix}/poster.jpg",
        sprite_path=f"{prefix}/sprite.jpg",
        thumbnail_vtt_path=f"{prefix}/thumbnails.vtt",
        sprite_meta=geometry,
    )
    video.refresh_from_db()
    progress.publish(video, ProcessingStage.THUMBNAILS, 1.0,
                     f"{geometry['tiles']} miniatures")
    return str(video.pk)


# --------------------------------------------------------------------------
# Stage 5 — publish
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.finalize_video")
def finalize_video(video_id: str) -> str:
    video = _load(video_id)
    progress.publish(video, ProcessingStage.PUBLISHING, 0.2, "Publication")

    # Belt and braces: refuse to flip to `ready` unless every artefact exists.
    missing = []
    if not video.hls_master_path:
        missing.append("manifeste principal")
    if not video.renditions.exists():
        missing.append("rendus")
    if not video.poster_path:
        missing.append("poster")
    for rendition in video.renditions.all():
        if not storage.object_exists(video.storage_bucket, rendition.hls_playlist_path):
            missing.append(f"manifeste {rendition.label}")
    if missing:
        raise RuntimeError("Elements manquants apres transcodage: " + ", ".join(missing))

    with transaction.atomic():
        video.status = VideoStatus.READY
        video.processing_stage = ProcessingStage.DONE
        video.processing_progress = 100
        video.failure_reason = ""
        if video.published_at is None:
            video.published_at = timezone.now()
        video.save(update_fields=["status", "processing_stage", "processing_progress",
                                  "failure_reason", "published_at", "updated_at"])
        UploadSession.objects.filter(video=video).update(status=UploadStatus.COMPLETED)

    # Index it the moment it becomes findable, not at the next beat tick.
    from apps.search.services import update_search_vector

    update_search_vector(video)

    pipeline.clear_work_dir(video)
    pipeline.drop_local_source(video)

    progress.publish(video, ProcessingStage.DONE, 1.0, "Video prete")
    progress.publish_terminal(video, "Video prete")
    logger.info("video %s is ready (%d renditions)", video.pk, video.renditions.count())
    return str(video.pk)


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.on_pipeline_failure")
def on_pipeline_failure(request, exc, traceback_str, video_id: str) -> None:
    """Terminal error handler for the chain.

    A partially-transcoded video is never left looking usable: the status becomes
    `failed`, the reason is stored where the uploader can read it, and the
    half-written objects are removed so a retry starts clean.
    """
    logger.error("transcoding pipeline failed for video %s: %s", video_id, exc)
    try:
        video = _load(video_id)
    except Video.DoesNotExist:
        return

    reason = str(exc) or "Erreur inconnue pendant le transcodage."
    video.mark_failed(reason)
    pipeline.clear_work_dir(video)
    pipeline.purge_derived_assets(video)
    video.renditions.all().delete()
    video.thumbnails.all().delete()

    progress.publish_terminal(video, reason)


# --------------------------------------------------------------------------
# Asset lifecycle
# --------------------------------------------------------------------------
@shared_task(name="videos.transcode.relocate_assets")
def relocate_assets(video_id: str) -> str:
    """Move a video's HLS tree between the public and private buckets.

    Triggered when visibility crosses the private <-> public/unlisted line. Without
    this, making a public video private would leave its segments anonymously
    readable in the public bucket — the manifest would be gated while the media
    stayed wide open.
    """
    video = _load(video_id)
    target = video.target_bucket
    current = video.storage_bucket

    if not current or current == target or not video.hls_master_path:
        return str(video.pk)

    moved = storage.move_prefix(current, target, video.asset_prefix)
    Video.objects.filter(pk=video.pk).update(storage_bucket=target)
    logger.info("Relocated %d objects for video %s: %s -> %s",
                moved, video.pk, current, target)
    return str(video.pk)


@shared_task(name="videos.transcode.delete_assets")
def delete_video_assets(video_id: str, asset_prefix: str) -> None:
    """Purge every object for a deleted video. Takes the prefix explicitly
    because the row is already gone by the time this runs."""
    for bucket in (settings.MINIO_PUBLIC_BUCKET, settings.MINIO_PRIVATE_BUCKET):
        try:
            storage.delete_prefix(bucket, asset_prefix)
            storage.delete_prefix(bucket, f"originals/{video_id}/")
        except Exception:
            logger.warning("Could not purge %s from %s", asset_prefix, bucket,
                           exc_info=True)


# --------------------------------------------------------------------------
# Maintenance (Celery beat)
# --------------------------------------------------------------------------
@shared_task(name="videos.maintenance.cleanup_abandoned_uploads")
def cleanup_abandoned_uploads() -> dict:
    """Expire tus sessions nobody finished and delete their scratch files."""
    now = timezone.now()
    stale = UploadSession.objects.filter(
        status=UploadStatus.IN_PROGRESS, expires_at__lt=now
    )

    removed = 0
    freed = 0
    for session in stale.iterator():
        path = Path(session.scratch_path)
        if path.exists():
            freed += path.stat().st_size
            path.unlink(missing_ok=True)
        removed += 1

    stale.update(status=UploadStatus.EXPIRED,
                 error="Session expiree sans televersement complet.")
    if removed:
        logger.info("Swept %d abandoned uploads (%.1f MiB freed)", removed,
                    freed / (1024 ** 2))
    return {"sessions_expired": removed, "bytes_freed": freed}


@shared_task(name="videos.maintenance.cleanup_stale_workdirs")
def cleanup_stale_workdirs() -> dict:
    """Remove transcode work directories with no matching in-flight video.

    Catches the case where a worker was killed mid-encode: the chain never
    reached `finalize_video`, so nothing cleaned up after it.
    """
    root = Path(settings.TRANSCODE_WORK_DIR)
    if not root.exists():
        return {"removed": 0}

    active = set(
        str(pk) for pk in Video.objects.filter(
            status=VideoStatus.PROCESSING
        ).values_list("pk", flat=True)
    )

    removed = 0
    for child in root.iterdir():
        if child.is_dir() and child.name not in active:
            import shutil

            shutil.rmtree(child, ignore_errors=True)
            removed += 1

    if removed:
        logger.info("Removed %d stale transcode work directories", removed)
    return {"removed": removed}
