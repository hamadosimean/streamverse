"""Infrastructure endpoints."""
from django.conf import settings
from django.db import connection
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness/readiness probe used by docker-compose healthchecks."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: dict}, tags=["system"])
    def get(self, request):
        checks = {}

        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:  # pragma: no cover - infra failure path
            checks["database"] = f"error: {exc}"

        try:
            cache.set("healthcheck", "1", 5)
            checks["redis"] = "ok" if cache.get("healthcheck") == "1" else "error"
        except Exception as exc:  # pragma: no cover
            checks["redis"] = f"error: {exc}"

        try:
            from apps.core import storage

            storage.internal_client().head_bucket(Bucket=settings.MINIO_PUBLIC_BUCKET)
            checks["object_storage"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["object_storage"] = f"error: {exc}"

        healthy = all(v == "ok" for v in checks.values())
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )
