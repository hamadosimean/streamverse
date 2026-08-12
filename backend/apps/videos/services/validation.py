"""Upload validation — the gate between "bytes arrived" and "enter the queue".

Nothing reaches a Celery worker until it passes here. Transcoding is the most
expensive thing this platform does; letting an unvalidated file into that queue
is how you get a denial-of-service for the price of one HTTP request.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import magic
from django.conf import settings

from apps.videos.services.ffmpeg import FFmpegError, ProbeResult, probe


class UploadRejected(Exception):
    """Validation failure with a message safe to show the uploader."""

    def __init__(self, message: str, code: str = "invalid_upload"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ValidationResult:
    mime_type: str
    size_bytes: int
    probe: ProbeResult


def validate_declared_size(size_bytes: int) -> None:
    """Checked at tus-creation time, before a single byte is accepted."""
    if size_bytes <= 0:
        raise UploadRejected("Taille de fichier invalide.", "invalid_size")
    if size_bytes > settings.MAX_UPLOAD_BYTES:
        limit_gb = settings.MAX_UPLOAD_BYTES / (1024 ** 3)
        raise UploadRejected(
            f"Fichier trop volumineux (maximum {limit_gb:.1f} Go).", "file_too_large"
        )


def validate_uploaded_file(path: str | Path) -> ValidationResult:
    """Full validation of a completed upload.

    Order is deliberate: cheap checks first, ffprobe last.
    """
    path = Path(path)
    if not path.exists():
        raise UploadRejected("Le fichier televerse est introuvable.", "missing_file")

    size = path.stat().st_size
    validate_declared_size(size)

    # Sniff the real type from the leading bytes. The browser-declared
    # Content-Type and the filename extension are both attacker-controlled.
    mime_type = magic.from_buffer(path.open("rb").read(2048), mime=True)
    if mime_type not in settings.ALLOWED_VIDEO_MIME_TYPES:
        raise UploadRejected(
            f"Type de fichier non autorise ({mime_type}). "
            f"Formats acceptes: MP4, MOV, MKV, WebM, AVI.",
            "unsupported_type",
        )

    # ffprobe is the real arbiter: a file can carry a valid MP4 magic number and
    # still contain nothing decodable.
    try:
        result = probe(path)
    except FFmpegError as exc:
        raise UploadRejected(str(exc), "unreadable_media") from exc

    if result.duration_seconds > settings.MAX_VIDEO_DURATION_SECONDS:
        limit_h = settings.MAX_VIDEO_DURATION_SECONDS / 3600
        raise UploadRejected(
            f"Video trop longue (maximum {limit_h:.1f} h).", "duration_too_long"
        )

    if result.width < 64 or result.height < 64:
        raise UploadRejected(
            "Resolution trop faible pour etre diffusee (minimum 64x64).",
            "resolution_too_small",
        )

    # 16K on the long side — beyond this, something is wrong with the file rather
    # than genuinely ambitious.
    if max(result.width, result.height) > 16384:
        raise UploadRejected("Resolution source aberrante.", "resolution_too_large")

    return ValidationResult(mime_type=mime_type, size_bytes=size, probe=result)
