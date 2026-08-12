"""Single entry point for writing audit entries.

Centralised so no call site has to remember to resolve the ContentType or to
snapshot the object repr.
"""
from __future__ import annotations

import logging

from django.contrib.contenttypes.models import ContentType

from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(action: str, *, actor=None, target=None, reason: str = "",
           metadata: dict | None = None, request=None) -> AuditLog:
    """Write one audit entry.

    Never raises into the caller: losing an audit row must not fail the user's
    action, but it must be loud in the logs.
    """
    try:
        content_type = None
        object_id = None
        object_repr = ""
        if target is not None:
            content_type = ContentType.objects.get_for_model(target.__class__)
            object_id = str(target.pk)
            object_repr = str(target)[:255]

        if actor is None and request is not None and request.user.is_authenticated:
            actor = request.user

        return AuditLog.objects.create(
            actor=actor,
            action=action,
            content_type=content_type,
            object_id=object_id,
            object_repr=object_repr,
            reason=reason or "",
            metadata=metadata or {},
            ip_address=_client_ip(request),
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit entry action=%s", action)
        raise
