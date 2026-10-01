"""Backend health endpoint — the WatchUp check target.

WatchUp points at backend endpoints only (design spec §2): configure it with
GET /api/health/ and alert on anything but HTTP 200 {"status": "ok"}.
"""

from django.db import connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None, responses=OpenApiTypes.OBJECT, tags=["health"], auth=[]
    )
    def get(self, request):
        checks = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["db"] = "ok"
        except Exception:
            checks["db"] = "error"
        try:
            from django.core.cache import cache

            cache.set("healthcheck", "ok", timeout=10)
            checks["cache"] = "ok" if cache.get("healthcheck") == "ok" else "error"
        except Exception:
            checks["cache"] = "error"
        try:
            import redis
            from django.conf import settings

            client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
            client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"

        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        return Response({"status": status, **checks})
