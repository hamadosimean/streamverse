"""Resumable upload endpoint implementing the tus 1.0.0 core protocol.

Why hand-rolled rather than a library: the maintained Django tus packages either
target older Django releases or hard-wire storage assumptions that conflict with
the MinIO layout here. The core protocol is four verbs and an offset counter, and
owning it keeps the completion hook (validate -> create Video -> queue the
pipeline) exactly where it belongs.

Supported extensions: `creation`, `expiration`, `termination`.

Flow:
    OPTIONS /api/uploads/            -> capability advertisement
    POST    /api/uploads/            -> 201 + Location of the new upload
    HEAD    /api/uploads/<id>/       -> current Upload-Offset (this is what makes
                                        a resume after a dropped connection work)
    PATCH   /api/uploads/<id>/       -> append bytes at Upload-Offset
    DELETE  /api/uploads/<id>/       -> abort and discard
"""
from __future__ import annotations

import base64
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import BaseParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from apps.videos.models import (
    UploadSession,
    UploadStatus,
    Video,
    VideoStatus,
    Visibility,
)
from apps.videos.services import pipeline
from apps.videos.services.validation import UploadRejected, validate_declared_size, validate_uploaded_file
from apps.videos.tasks import start_transcoding_pipeline

logger = logging.getLogger(__name__)

TUS_VERSION = "1.0.0"
TUS_EXTENSIONS = "creation,expiration,termination"


class TusUploadParser(BaseParser):
    """Pass the PATCH body through untouched.

    DRF would otherwise reject `application/offset+octet-stream` as an
    unsupported media type before the view ever runs.
    """

    media_type = "application/offset+octet-stream"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


def _tus_headers(extra: dict | None = None) -> dict:
    headers = {
        "Tus-Resumable": TUS_VERSION,
        "Cache-Control": "no-store",
    }
    headers.update(extra or {})
    return headers


def _parse_upload_metadata(raw: str) -> dict:
    """Decode the tus `Upload-Metadata` header (`key b64value,key2 b64value2`)."""
    metadata: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split(" ", 1)
        key = parts[0]
        if len(parts) == 1:
            metadata[key] = ""
            continue
        try:
            metadata[key] = base64.b64decode(parts[1]).decode("utf-8", "replace")
        except Exception:
            metadata[key] = ""
    return metadata


def _scratch_path(session_id) -> Path:
    directory = Path(settings.UPLOAD_SCRATCH_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{session_id}.part"


@extend_schema(exclude=True)  # tus is not a REST resource; documented in the README
class TusCollectionView(APIView):
    """`OPTIONS` (capabilities) and `POST` (create an upload)."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "upload"

    def options(self, request, *args, **kwargs):
        return HttpResponse(
            status=status.HTTP_204_NO_CONTENT,
            headers=_tus_headers(
                {
                    "Tus-Version": TUS_VERSION,
                    "Tus-Extension": TUS_EXTENSIONS,
                    "Tus-Max-Size": str(settings.MAX_UPLOAD_BYTES),
                }
            ),
        )

    def post(self, request, *args, **kwargs):
        raw_length = request.headers.get("Upload-Length")
        if not raw_length or not raw_length.isdigit():
            raise ValidationError({"Upload-Length": "En-tete obligatoire et numerique."})

        upload_length = int(raw_length)
        try:
            # Reject an oversized upload before accepting any bytes at all.
            validate_declared_size(upload_length)
        except UploadRejected as exc:
            raise ValidationError({"detail": exc.message, "code": exc.code}) from exc

        metadata = _parse_upload_metadata(request.headers.get("Upload-Metadata", ""))
        filename = (metadata.get("filename") or metadata.get("name") or "video")[:255]

        session = UploadSession.objects.create(
            user=request.user,
            filename=filename,
            upload_length=upload_length,
            metadata=metadata,
            scratch_path="",
            expires_at=timezone.now() + timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS),
        )
        path = _scratch_path(session.pk)
        path.touch()
        session.scratch_path = str(path)
        session.save(update_fields=["scratch_path"])

        location = request.build_absolute_uri(f"/api/uploads/{session.pk}/")
        logger.info("tus upload created id=%s user=%s bytes=%d",
                    session.pk, request.user.username, upload_length)

        return HttpResponse(
            status=status.HTTP_201_CREATED,
            headers=_tus_headers(
                {
                    "Location": location,
                    "Upload-Expires": session.expires_at.strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    ),
                }
            ),
        )


@extend_schema(exclude=True)
class TusUploadView(APIView):
    """`HEAD`, `PATCH` and `DELETE` on a single upload."""

    permission_classes = [IsAuthenticated]
    parser_classes = [TusUploadParser]

    def get_session(self, request, upload_id) -> UploadSession:
        try:
            session = UploadSession.objects.select_related("user").get(pk=upload_id)
        except (UploadSession.DoesNotExist, ValueError, TypeError):
            raise NotFound("Session de televersement inconnue.")
        # Ownership, every time — an upload id is not a capability.
        if session.user_id != request.user.pk:
            raise PermissionDenied("Cette session de televersement ne vous appartient pas.")
        return session

    def options(self, request, *args, **kwargs):
        return HttpResponse(
            status=status.HTTP_204_NO_CONTENT,
            headers=_tus_headers({"Tus-Version": TUS_VERSION,
                                  "Tus-Extension": TUS_EXTENSIONS}),
        )

    def head(self, request, upload_id, *args, **kwargs):
        session = self.get_session(request, upload_id)
        if session.status in (UploadStatus.ABORTED, UploadStatus.EXPIRED):
            raise NotFound("Session de televersement expiree.")
        return HttpResponse(
            status=status.HTTP_200_OK,
            headers=_tus_headers(
                {
                    "Upload-Offset": str(session.offset),
                    "Upload-Length": str(session.upload_length),
                }
            ),
        )

    def patch(self, request, upload_id, *args, **kwargs):
        session = self.get_session(request, upload_id)

        if session.status != UploadStatus.IN_PROGRESS:
            raise ValidationError({"detail": "Cette session n'accepte plus de donnees."})

        raw_offset = request.headers.get("Upload-Offset")
        if raw_offset is None or not raw_offset.isdigit():
            raise ValidationError({"Upload-Offset": "En-tete obligatoire et numerique."})

        client_offset = int(raw_offset)
        if client_offset != session.offset:
            # 409 is what tells tus-js-client to re-HEAD and resume from the truth.
            return HttpResponse(
                status=status.HTTP_409_CONFLICT,
                headers=_tus_headers({"Upload-Offset": str(session.offset)}),
            )

        chunk = request.data if isinstance(request.data, (bytes, bytearray)) else b""
        if not chunk:
            return HttpResponse(
                status=status.HTTP_204_NO_CONTENT,
                headers=_tus_headers({"Upload-Offset": str(session.offset)}),
            )

        new_offset = session.offset + len(chunk)
        if new_offset > session.upload_length:
            raise ValidationError(
                {"detail": "Les donnees depassent la taille annoncee."}
            )

        path = Path(session.scratch_path)
        # Seek-and-write rather than append: if a previous PATCH was interrupted
        # after the bytes hit the disk but before the offset was committed, the
        # retransmitted chunk overwrites cleanly instead of duplicating.
        with path.open("r+b" if path.exists() else "wb") as handle:
            handle.seek(session.offset)
            handle.write(chunk)

        UploadSession.objects.filter(pk=session.pk).update(offset=new_offset)
        session.offset = new_offset

        if session.is_complete:
            try:
                video = complete_upload(session, request)
            except UploadRejected as exc:
                session.status = UploadStatus.ABORTED
                session.error = exc.message
                session.save(update_fields=["status", "error", "updated_at"])
                Path(session.scratch_path).unlink(missing_ok=True)
                raise ValidationError({"detail": exc.message, "code": exc.code}) from exc

            return HttpResponse(
                status=status.HTTP_204_NO_CONTENT,
                headers=_tus_headers(
                    {
                        "Upload-Offset": str(session.offset),
                        # Non-standard, but it saves the client a round-trip to
                        # discover which Video the upload became.
                        "StreamVerse-Video-Id": str(video.pk),
                    }
                ),
            )

        return HttpResponse(
            status=status.HTTP_204_NO_CONTENT,
            headers=_tus_headers({"Upload-Offset": str(session.offset)}),
        )

    def delete(self, request, upload_id, *args, **kwargs):
        session = self.get_session(request, upload_id)
        Path(session.scratch_path).unlink(missing_ok=True)
        session.status = UploadStatus.ABORTED
        session.error = "Abandonne par l'utilisateur."
        session.save(update_fields=["status", "error", "updated_at"])
        return HttpResponse(status=status.HTTP_204_NO_CONTENT, headers=_tus_headers())


@extend_schema(tags=["upload"], responses={200: dict})
class UploadSessionResultView(APIView):
    """Which `Video` did this upload become?

    The final PATCH already answers this in a `StreamVerse-Video-Id` response
    header, but that header is non-standard and some proxies strip unknown ones.
    This is the fallback the client falls back to.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, upload_id):
        try:
            session = UploadSession.objects.select_related("video").get(pk=upload_id)
        except (UploadSession.DoesNotExist, ValueError, TypeError):
            raise NotFound("Session de televersement inconnue.")
        if session.user_id != request.user.pk:
            raise PermissionDenied("Cette session ne vous appartient pas.")

        return Response(
            {
                "upload_id": str(session.pk),
                "status": session.status,
                "video_id": str(session.video_id) if session.video_id else None,
                "error": session.error,
            }
        )


@transaction.atomic
def complete_upload(session: UploadSession, request=None) -> Video:
    """Validate the finished file, create the `Video`, queue the pipeline.

    Validation is synchronous so the uploader learns immediately that their file
    is unusable, instead of watching a progress bar for a minute and then being
    told. The *expensive* work — everything after this point — is Celery's.
    """
    scratch = Path(session.scratch_path)
    result = validate_uploaded_file(scratch)

    metadata = session.metadata or {}
    title = (metadata.get("title") or Path(session.filename).stem or "Sans titre")[:200]

    video = Video.objects.create(
        uploader=session.user,
        title=title,
        description=(metadata.get("description") or "")[:5000],
        status=VideoStatus.PROCESSING,
        # Private until the uploader explicitly publishes. Nothing goes public by
        # accident because a form field defaulted the wrong way.
        visibility=Visibility.PRIVATE,
        original_filename=session.filename,
        original_size_bytes=result.size_bytes,
        original_mime_type=result.mime_type,
        duration_seconds=int(round(result.probe.duration_seconds)),
        source_width=result.probe.width,
        source_height=result.probe.height,
        source_resolution=result.probe.resolution,
        source_video_codec=result.probe.video_codec,
        source_audio_codec=result.probe.audio_codec,
        has_audio=result.probe.has_audio,
    )

    # Move the scratch file to its stable, video-keyed location so the worker can
    # find it by id alone.
    destination = pipeline.local_source_path(video)
    scratch.replace(destination)

    session.video = video
    session.status = UploadStatus.COMPLETED
    session.scratch_path = str(destination)
    session.save(update_fields=["video", "status", "scratch_path", "updated_at"])

    audit.record(
        AuditAction.VIDEO_UPLOADED,
        actor=session.user,
        target=video,
        metadata={
            "filename": session.filename,
            "size_bytes": result.size_bytes,
            "mime_type": result.mime_type,
            "resolution": result.probe.resolution,
        },
        request=request,
    )

    # Queue only once the transaction that created the Video has committed —
    # otherwise the worker can look the row up before it exists.
    transaction.on_commit(lambda: start_transcoding_pipeline.delay(str(video.pk)))

    logger.info("upload %s completed -> video %s (%s)", session.pk, video.pk,
                result.probe.resolution)
    return video
