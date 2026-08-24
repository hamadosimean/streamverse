"""Validation for the two profile images a user can upload.

Everything here is enforced server-side. The upload form resizes and checks the
file before sending it, but that is a courtesy to the user's bandwidth — the
request that actually reaches this code may not have come from that form.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

# Pillow format name -> the MIME type we accept it as. Anything Pillow opens but
# that is missing here (BMP, TIFF, HEIC...) is rejected: the browser support is
# uneven and the file is usually far larger than an equivalent WebP.
_FORMAT_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}

_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _human_size(num_bytes: int) -> str:
    mib = num_bytes / (1024 * 1024)
    return f"{mib:.0f} Mo" if mib >= 1 else f"{num_bytes / 1024:.0f} Ko"


def validate_profile_image(uploaded, *, max_bytes: int, max_dimension: int) -> str:
    """Check one uploaded image and return the extension it should be saved with.

    The type is decided by *decoding* the file, never by its declared
    `content_type` or its filename: both are client-supplied strings, and a
    `.png` that Pillow refuses to open has no business in the public bucket.
    """
    if uploaded.size == 0:
        raise serializers.ValidationError(_("Le fichier est vide."))

    if uploaded.size > max_bytes:
        raise serializers.ValidationError(
            _("Image trop lourde (%(size)s). Maximum: %(max)s.")
            % {"size": _human_size(uploaded.size), "max": _human_size(max_bytes)}
        )

    try:
        with Image.open(uploaded) as image:
            image.verify()  # cheap structural check; consumes the file object
        uploaded.seek(0)
        with Image.open(uploaded) as image:
            image_format, (width, height) = image.format, image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise serializers.ValidationError(
            _("Fichier illisible ou corrompu. Formats acceptes: JPG, PNG, WebP, GIF.")
        ) from exc
    finally:
        uploaded.seek(0)

    mime = _FORMAT_MIME.get(image_format or "")
    if mime is None or mime not in settings.ALLOWED_IMAGE_MIME_TYPES:
        raise serializers.ValidationError(
            _("Format non supporte. Formats acceptes: JPG, PNG, WebP, GIF.")
        )

    if max(width, height) > max_dimension:
        raise serializers.ValidationError(
            _("Image trop grande (%(w)dx%(h)d px). Maximum: %(max)d px de cote.")
            % {"w": width, "h": height, "max": max_dimension}
        )

    return _EXTENSION[mime]
