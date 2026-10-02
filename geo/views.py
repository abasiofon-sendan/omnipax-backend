from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from core.permissions import IsAdminRole

from .models import Corridor, Junction, RestrictedZone
from .serializers import (
    CorridorSerializer,
    JunctionSerializer,
    RestrictedZoneSerializer,
)


class CorridorViewSet(viewsets.ModelViewSet):
    queryset = Corridor.objects.all().order_by("name")
    serializer_class = CorridorSerializer
    permission_classes = [IsAdminRole]


class JunctionViewSet(viewsets.ModelViewSet):
    queryset = Junction.objects.select_related("corridor").all().order_by("name")
    serializer_class = JunctionSerializer
    permission_classes = [IsAdminRole]


class RestrictedZoneViewSet(viewsets.ModelViewSet):
    queryset = RestrictedZone.objects.all().order_by("-effective_date")
    serializer_class = RestrictedZoneSerializer
    permission_classes = [IsAdminRole]


class PublicCorridorViewSet(viewsets.ReadOnlyModelViewSet):
    """Public read-only feed for passenger/driver maps (no admin JWT needed).

    Only active corridors are exposed.
    """

    queryset = Corridor.objects.filter(is_active=True).order_by("name")
    serializer_class = CorridorSerializer
    permission_classes = [AllowAny]


class PublicJunctionViewSet(viewsets.ReadOnlyModelViewSet):
    """Public read-only feed for map anchors + client-side pin validation."""

    queryset = (
        Junction.objects.filter(is_active=True)
        .select_related("corridor")
        .order_by("name")
    )
    serializer_class = JunctionSerializer
    permission_classes = [AllowAny]


class PublicRestrictedZoneViewSet(viewsets.ReadOnlyModelViewSet):
    """Public read-only feed so clients can pre-check pins client-side."""

    queryset = RestrictedZone.objects.filter(is_active=True).order_by(
        "-effective_date"
    )
    serializer_class = RestrictedZoneSerializer
    permission_classes = [AllowAny]
