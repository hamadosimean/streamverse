"""Uniform API error envelope.

Every error response is `{"detail": str, "code": str, "errors": {...}|null}` so
the frontend interceptor has exactly one shape to handle.
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {"detail": "Erreur interne du serveur.", "code": "server_error",
             "errors": None},
            status=500,
        )

    data = response.data
    code = getattr(exc, "default_code", "error")

    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        response.data = {"detail": str(data["detail"]), "code": code, "errors": None}
    elif isinstance(data, dict):
        # Field-level validation errors.
        response.data = {
            "detail": "Les donnees envoyees sont invalides.",
            "code": code,
            "errors": data,
        }
    else:
        response.data = {"detail": str(data), "code": code, "errors": None}

    return response
