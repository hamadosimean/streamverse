"""Filesystem/storage plumbing shared by the transcoding tasks."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from django.conf import settings

from apps.core import storage
from apps.videos.models import Video

logger = logging.getLogger(__name__)


def sources_dir() -> Path:
    path = Path(settings.UPLOAD_SCRATCH_DIR) / "sources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_source_path(video: Video) -> Path:
    suffix = Path(video.original_filename or "").suffix.lower() or ".bin"
    return sources_dir() / f"{video.pk}{suffix}"


def work_dir(video: Video) -> Path:
    path = Path(settings.TRANSCODE_WORK_DIR) / str(video.pk)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_work_dir(video: Video) -> None:
    shutil.rmtree(Path(settings.TRANSCODE_WORK_DIR) / str(video.pk), ignore_errors=True)


def ensure_local_source(video: Video) -> Path:
    """Return a local path to the original file, downloading it if necessary.

    The happy path is a cache hit: the web container wrote the upload into a
    volume the worker also mounts. The download branch covers a retry days later,
    a worker on another host, or the scratch volume having been swept.
    """
    path = local_source_path(video)
    if path.exists() and path.stat().st_size > 0:
        return path

    if not video.original_key:
        raise FileNotFoundError(
            "Le fichier source est introuvable et n'a pas ete archive."
        )

    logger.info("Fetching original for video %s from object storage", video.pk)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.internal_client().download_file(
        settings.MINIO_PRIVATE_BUCKET, video.original_key, str(path)
    )
    return path


def archive_original(video: Video, source: Path) -> str:
    """Store the untouched upload in the private bucket.

    Always private, whatever the video's visibility: the original is only ever
    read by a worker (retry, or Phase 4's live-recording conversion), never by a
    browser.
    """
    key = f"originals/{video.pk}/source{source.suffix or '.bin'}"
    if not storage.object_exists(settings.MINIO_PRIVATE_BUCKET, key):
        storage.upload_file(source, settings.MINIO_PRIVATE_BUCKET, key)
    return key


def purge_derived_assets(video: Video) -> None:
    """Delete every rendition/thumbnail for a video from both buckets.

    Both buckets, unconditionally: a video whose visibility changed mid-failure
    could have left objects behind in either one.
    """
    for bucket in (settings.MINIO_PUBLIC_BUCKET, settings.MINIO_PRIVATE_BUCKET):
        try:
            storage.delete_prefix(bucket, video.asset_prefix)
        except Exception:
            logger.warning("Could not purge %s from %s", video.asset_prefix, bucket,
                           exc_info=True)


def purge_original(video: Video) -> None:
    if video.original_key:
        try:
            storage.delete_prefix(settings.MINIO_PRIVATE_BUCKET, f"originals/{video.pk}/")
        except Exception:
            logger.warning("Could not purge original for %s", video.pk, exc_info=True)


def drop_local_source(video: Video) -> None:
    """Free the scratch copy once the encode succeeded; MinIO holds the archive."""
    try:
        local_source_path(video).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove scratch source for %s", video.pk)


class ThrottledProgress:
    """Rate-limit WebSocket progress frames.

    ffmpeg emits a progress line roughly every frame. Forwarding all of them
    would flood the channel layer and buy the user nothing, since the bar cannot
    render faster than the screen refreshes.
    """

    def __init__(self, publish_fn, min_percent_delta: int = 1,
                 min_interval_seconds: float = 1.0):
        self._publish = publish_fn
        self._min_delta = min_percent_delta
        self._min_interval = min_interval_seconds
        self._last_percent = -1
        self._last_time = 0.0

    def __call__(self, fraction: float, *, force: bool = False) -> None:
        percent = int(fraction * 100)
        now = time.monotonic()
        if (
            force
            or percent >= self._last_percent + self._min_delta
            and now - self._last_time >= self._min_interval
        ):
            self._last_percent = percent
            self._last_time = now
            self._publish(fraction)
