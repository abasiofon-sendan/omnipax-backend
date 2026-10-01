from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Pin
from .serializers import PinCreateSerializer, PinSerializer
from .services import create_pin


def pin_error(exc):
    code = getattr(exc, "code", None) or "invalid"
    http_status = (
        status.HTTP_403_FORBIDDEN if code == "restricted_zone" else status.HTTP_400_BAD_REQUEST
    )
    return Response(
        {"detail": exc.messages[0] if exc.messages else str(exc), "code": code},
        status=http_status,
    )


class PinCreateView(APIView):
    serializer_class = PinCreateSerializer

    @extend_schema(request=PinCreateSerializer, responses=PinSerializer, tags=["pins"])
    def post(self, request):
        serializer = PinCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pin = create_pin(passenger=request.user, **serializer.validated_data)
        except ValidationError as exc:
            return pin_error(exc)
        return Response(PinSerializer(pin).data, status=status.HTTP_201_CREATED)


class ActivePinView(APIView):
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer, tags=["pins"])
    def get(self, request):
        pin = (
            Pin.objects.filter(
                passenger=request.user, status__in=Pin.LIVE_STATUSES
            )
            .select_related("junction", "corridor")
            .order_by("-created_at")
            .first()
        )
        if pin is None:
            return Response(
                {"detail": "No active pin."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(PinSerializer(pin).data)


class PinCancelView(APIView):
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer, tags=["pins"])
    def post(self, request, pin_id):
        pin = get_object_or_404(Pin, id=pin_id, passenger=request.user)
        if pin.status != Pin.Status.ACTIVE:
            return Response(
                {"detail": f"Only active pins can be cancelled (status={pin.status})."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        pin.status = Pin.Status.CANCELLED
        pin.save(update_fields=["status"])
        from realtime.broadcast import publish_demand, publish_pin_event

        publish_demand(pin.junction_id)
        publish_pin_event(pin.junction_id, "cancelled", pin.id)
        return Response(PinSerializer(pin).data)


class PinStatusView(APIView):
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer, tags=["pins"])
    def get(self, request, pin_id):
        pin = get_object_or_404(Pin, id=pin_id, passenger=request.user)
        return Response(PinSerializer(pin).data)
