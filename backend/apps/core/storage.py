"""MinIO / S3 object-store helper.

Why this exists instead of using django-storages everywhere: the transcoder emits
*trees* of files (hundreds of HLS segments per rendition) that are never bound to
a Django FileField. We need direct, bulk, content-type-aware object operations,
plus presigning against a different host than the one we upload through.

Two clients, deliberately:

  * ``internal`` — endpoint ``http://minio:9000``. Used by Django and the Celery
    workers inside the compose network for PUT/GET/COPY/DELETE.
  * ``public``   — endpoint ``http://localhost:9010`` (whatever the browser can
    reach). Used ONLY to generate presigned URLs and public URLs. SigV4 signs the
    Host header, so a URL presigned against ``minio:9000`` would fail signature
    validation when the browser sends ``Host: localhost:9010``.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# HLS-specific content types the stdlib does not know reliably.
EXTRA_CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".m4s": "video/iso.segment",
    ".mp4": "video/mp4",
    ".vtt": "text/vtt",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".json": "application/json",
}


def content_type_for(path: str | os.PathLike) -> str:
    ext = Path(path).suffix.lower()
    if ext in EXTRA_CONTENT_TYPES:
        return EXTRA_CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _build_client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


@lru_cache(maxsize=2)
def _client(kind: str):
    endpoint = (
        settings.MINIO_ENDPOINT if kind == "internal" else settings.MINIO_PUBLIC_ENDPOINT
    )
    return _build_client(endpoint)


def internal_client():
    """Client for server-side reads/writes inside the docker network."""
    return _client("internal")


def signing_client():
    """Client whose endpoint matches what the browser will actually request."""
    return _client("public")


# --------------------------------------------------------------------------
# Bucket provisioning
# --------------------------------------------------------------------------
PUBLIC_READ_POLICY = """{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::%(bucket)s/*"]
    }
  ]
}"""


def ensure_buckets() -> None:
    """Create both buckets and apply explicit policies.

    MinIO's default for a fresh bucket is *private*, which is right for the
    private bucket but wrong for the public one; and we never want to leave the
    public bucket at 'whatever MinIO defaulted to'. Both are set explicitly.
    """
    client = internal_client()

    for bucket in (settings.MINIO_PUBLIC_BUCKET, settings.MINIO_PRIVATE_BUCKET):
        try:
            client.head_bucket(Bucket=bucket)
            logger.info("MinIO bucket already present: %s", bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "403"):
                raise
            client.create_bucket(Bucket=bucket)
            logger.info("MinIO bucket created: %s", bucket)

    # Public bucket: anonymous GET on objects only. No LIST — browsing the
    # bucket index would expose unlisted video IDs.
    client.put_bucket_policy(
        Bucket=settings.MINIO_PUBLIC_BUCKET,
        Policy=PUBLIC_READ_POLICY % {"bucket": settings.MINIO_PUBLIC_BUCKET},
    )
    logger.info("Public-read policy applied to %s", settings.MINIO_PUBLIC_BUCKET)

    # Private bucket: strip any policy so only signed requests succeed.
    try:
        client.delete_bucket_policy(Bucket=settings.MINIO_PRIVATE_BUCKET)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise
    logger.info("Private bucket %s left signature-only", settings.MINIO_PRIVATE_BUCKET)

    # CORS so hls.js can fetch manifests/segments cross-origin from :9010.
    cors = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedOrigins": ["*"],
                "ExposeHeaders": ["Content-Length", "Content-Range", "ETag"],
                "MaxAgeSeconds": 3600,
            }
        ]
    }
    for bucket in (settings.MINIO_PUBLIC_BUCKET, settings.MINIO_PRIVATE_BUCKET):
        try:
            client.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors)
        except ClientError:
            logger.warning("Could not set CORS on %s (non-fatal)", bucket)


# --------------------------------------------------------------------------
# Object operations
# --------------------------------------------------------------------------
def upload_file(local_path: str | os.PathLike, bucket: str, key: str,
                cache_control: str | None = None) -> None:
    extra = {"ContentType": content_type_for(local_path)}
    if cache_control:
        extra["CacheControl"] = cache_control
    internal_client().upload_file(str(local_path), bucket, key, ExtraArgs=extra)


def upload_bytes(data: bytes, bucket: str, key: str,
                 content_type: str | None = None) -> None:
    internal_client().put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type or content_type_for(key),
    )


def upload_directory(local_dir: str | os.PathLike, bucket: str, prefix: str) -> int:
    """Upload a directory tree, preserving relative paths under ``prefix``.

    Segments get a long cache lifetime (immutable, content-addressed by name);
    manifests get a short one so a rendition added later is picked up.
    """
    local_dir = Path(local_dir)
    count = 0
    for path in sorted(local_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(local_dir).as_posix()
        cache = "public, max-age=60" if path.suffix == ".m3u8" else "public, max-age=31536000, immutable"
        upload_file(path, bucket, f"{prefix.rstrip('/')}/{rel}", cache_control=cache)
        count += 1
    return count


def get_text(bucket: str, key: str) -> str:
    obj = internal_client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8")


def object_exists(bucket: str, key: str) -> bool:
    try:
        internal_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def iter_keys(bucket: str, prefix: str) -> Iterator[str]:
    paginator = internal_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            yield item["Key"]


def delete_prefix(bucket: str, prefix: str) -> int:
    """Delete every object under a prefix. Used on video delete and on retry."""
    client = internal_client()
    deleted = 0
    batch: list[dict] = []
    for key in iter_keys(bucket, prefix):
        batch.append({"Key": key})
        if len(batch) == 1000:
            client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted += len(batch)
            batch = []
    if batch:
        client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        deleted += len(batch)
    return deleted


def move_prefix(src_bucket: str, dst_bucket: str, prefix: str) -> int:
    """Server-side copy then delete — used when a video's visibility changes
    between private (private bucket) and public/unlisted (public bucket)."""
    if src_bucket == dst_bucket:
        return 0
    client = internal_client()
    moved = 0
    for key in list(iter_keys(src_bucket, prefix)):
        client.copy_object(
            Bucket=dst_bucket,
            Key=key,
            CopySource={"Bucket": src_bucket, "Key": key},
            MetadataDirective="COPY",
        )
        moved += 1
    delete_prefix(src_bucket, prefix)
    return moved


# --------------------------------------------------------------------------
# URL generation
# --------------------------------------------------------------------------
def public_url(key: str, bucket: str | None = None) -> str:
    """Unsigned, permanent URL for an object in the public-read bucket."""
    bucket = bucket or settings.MINIO_PUBLIC_BUCKET
    base = settings.MINIO_PUBLIC_ENDPOINT.rstrip("/")
    return f"{base}/{bucket}/{key.lstrip('/')}"


def presigned_url(key: str, bucket: str | None = None,
                  ttl: int | None = None) -> str:
    """Short-lived signed URL for an object in the private bucket.

    Signed with the *public* endpoint so the Host in the signature matches what
    the browser sends.
    """
    bucket = bucket or settings.MINIO_PRIVATE_BUCKET
    ttl = ttl or settings.MINIO_PRESIGN_TTL_SECONDS
    return signing_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl,
    )


def presign_many(keys: Iterable[str], bucket: str | None = None,
                 ttl: int | None = None) -> dict[str, str]:
    """Presign a batch of keys. Purely local HMAC work — no network round-trips,
    which is what makes per-segment presigning affordable."""
    return {key: presigned_url(key, bucket=bucket, ttl=ttl) for key in keys}
