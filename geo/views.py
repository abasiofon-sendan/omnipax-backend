from rest_framework import viewsets

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
