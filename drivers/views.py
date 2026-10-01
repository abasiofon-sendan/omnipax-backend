from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.geo_utils import inside_bbox
from core.permissions import IsAdminRole
from geo.models import Corridor
from rides.models import EmergencyPage, Pin
from rides.serializers import PinSerializer
from rides.services import release_reservation

from .models import DriverLocation, DriverProfile
from .serializers import (
    DriverLocationSerializer,
    DriverProfileSerializer,
    DriverRegisterSerializer,
    DriverVerifySerializer,
    LocationSerializer,
    OnlineToggleSerializer,
    PinCompleteSerializer,
)
from .visibility import junction_heatmap


class IsDriverRole(BasePermission):
    message = "Driver account required."

    def has_permission(self, request, view):
        user = request.user
        return (
            bool(user and user.is_authenticated)
            and getattr(user, "role", None) == User.Role.DRIVER
        )


class DriverRegisterView(APIView):
    """Authenticated user attaches a driver profile (starts `pending`).

    (Source spec sketched this with a phone payload; since accounts now carry
    the phone on the User, only profile fields are needed here.)
    """

    serializer_class = DriverRegisterSerializer

    @extend_schema(
        request=DriverRegisterSerializer,
        responses=DriverProfileSerializer,
        tags=["drivers"],
    )
    def post(self, request):
        if hasattr(request.user, "driver_profile"):
            return Response(
                {"detail": "Driver profile already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = DriverRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            corridor = Corridor.objects.get(
                id=serializer.validated_data["approved_corridor_id"], is_active=True
            )
        except Corridor.DoesNotExist:
            return Response(
                {"detail": "Unknown or inactive corridor."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            profile = DriverProfile.objects.create(
                user=request.user,
                registration_id=serializer.validated_data["registration_id"],
                vehicle_type=serializer.validated_data["vehicle_type"],
                plate_number=serializer.validated_data["plate_number"],
                approved_corridor=corridor,
            )
            request.user.role = User.Role.DRIVER
            request.user.save(update_fields=["role"])
        return Response(
            DriverProfileSerializer(profile).data, status=status.HTTP_201_CREATED
        )


class DriverVerifyView(APIView):
    """Admin-only: manual approval queue (pluggable strategy, spec §8)."""

    permission_classes = [IsAdminRole]
    serializer_class = DriverVerifySerializer

    @extend_schema(
        request=DriverVerifySerializer,
        responses=DriverProfileSerializer,
        tags=["drivers"],
    )
    def post(self, request):
        serializer = DriverVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = DriverProfile.objects.get(
                id=serializer.validated_data["driver_id"]
            )
        except DriverProfile.DoesNotExist:
            return Response(
                {"detail": "Unknown driver."}, status=status.HTTP_404_NOT_FOUND
            )
        action = serializer.validated_data["action"]
        profile.verification_status = (
            DriverProfile.VerificationStatus.VERIFIED
            if action == "verify"
            else DriverProfile.VerificationStatus.REJECTED
        )
        profile.save(update_fields=["verification_status"])
        return Response(DriverProfileSerializer(profile).data)


class LocationHeartbeatView(APIView):
    """Upsert current location. Clients call every 15-30s while online."""

    permission_classes = [IsDriverRole]
    serializer_class = LocationSerializer

    @extend_schema(
        request=LocationSerializer,
        responses=DriverLocationSerializer,
        tags=["drivers"],
    )
    def post(self, request):
        serializer = LocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lat = float(serializer.validated_data["latitude"])
        lng = float(serializer.validated_data["longitude"])
        if not inside_bbox(lat, lng):
            return Response(
                {"detail": "Coordinates outside service area."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            profile = request.user.driver_profile
        except DriverProfile.DoesNotExist:
            return Response(
                {"detail": "No driver profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        location, _ = DriverLocation.objects.update_or_create(
            driver=profile,
            defaults={
                "latitude": serializer.validated_data["latitude"],
                "longitude": serializer.validated_data["longitude"],
                "accuracy_meters": serializer.validated_data.get("accuracy_meters"),
                "recorded_at": timezone.now(),
            },
        )
        return Response(DriverLocationSerializer(location).data)


class OnlineToggleView(APIView):
    permission_classes = [IsDriverRole]
    serializer_class = OnlineToggleSerializer

    @extend_schema(
        request=OnlineToggleSerializer,
        responses=DriverProfileSerializer,
        tags=["drivers"],
    )
    def post(self, request):
        serializer = OnlineToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = request.user.driver_profile
        except DriverProfile.DoesNotExist:
            return Response(
                {"detail": "No driver profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile.is_online = serializer.validated_data["is_online"]
        profile.save(update_fields=["is_online"])
        return Response(DriverProfileSerializer(profile).data)


class ZonesView(APIView):
    """Primary driver interface: ranked top-3 + full heatmap demand array."""

    permission_classes = [IsDriverRole]
    serializer_class = DriverLocationSerializer

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["drivers"])
    def get(self, request):
        return Response(junction_heatmap())


class DriverPinsView(APIView):
    """NOT a request inbox: pins this driver was alerted to / may complete."""

    permission_classes = [IsDriverRole]
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer(many=True), tags=["drivers"])
    def get(self, request):
        try:
            profile = request.user.driver_profile
        except DriverProfile.DoesNotExist:
            return Response([])
        pins = (
            Pin.objects.filter(
                visibility__driver=profile, status__in=Pin.LIVE_STATUSES
            )
            .select_related("junction", "corridor")
            .order_by("-created_at")
            .distinct()
        )
        return Response(PinSerializer(pins, many=True).data)


def _driver_profile_or_400(request):
    try:
        return request.user.driver_profile, None
    except DriverProfile.DoesNotExist:
        return None, Response(
            {"detail": "No driver profile."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _live_pin_or_400(pin_id):
    try:
        pin = Pin.objects.select_related("junction", "corridor").get(id=pin_id)
    except (Pin.DoesNotExist, ValueError):
        return None, Response(
            {"detail": "Unknown pin."}, status=status.HTTP_404_NOT_FOUND
        )
    if pin.status not in Pin.LIVE_STATUSES:
        return None, Response(
            {"detail": f"Pin is {pin.status}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if pin.expires_at < timezone.now():
        return None, Response(
            {"detail": "Pin has expired."}, status=status.HTTP_400_BAD_REQUEST
        )
    return pin, None


class PinAcceptView(APIView):
    """Paged driver accepts within the deadline → pin `reserved`."""

    permission_classes = [IsDriverRole]
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer, tags=["drivers"])
    def post(self, request, pin_id):
        profile, err = _driver_profile_or_400(request)
        if err:
            return err
        pin, err = _live_pin_or_400(pin_id)
        if err:
            return err
        if pin.status != Pin.Status.ACTIVE:
            return Response(
                {"detail": "Pin is no longer available."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        page = EmergencyPage.objects.filter(
            pin=pin, driver=profile, outcome=EmergencyPage.Outcome.PAGED
        ).first()
        if page is None:
            return Response(
                {"detail": "No emergency page for this driver."},
                status=status.HTTP_403_FORBIDDEN,
            )
        now = timezone.now()
        if pin.reservation_expires_at and pin.reservation_expires_at < now:
            page.outcome = EmergencyPage.Outcome.EXPIRED
            page.resolved_at = now
            page.save(update_fields=["outcome", "resolved_at"])
            return Response(
                {"detail": "Accept window has passed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            page.outcome = EmergencyPage.Outcome.ACCEPTED
            page.resolved_at = now
            page.save(update_fields=["outcome", "resolved_at"])
            pin.status = Pin.Status.RESERVED
            pin.reserved_by = profile
            pin.reserved_at = now
            pin.reservation_expires_at = None  # accept window is moot once held
            pin.save(
                update_fields=[
                    "status",
                    "reserved_by",
                    "reserved_at",
                    "reservation_expires_at",
                ]
            )
        from realtime.broadcast import publish_demand, publish_pin_event

        publish_demand(pin.junction_id)
        publish_pin_event(pin.junction_id, "reserved", pin.id)
        return Response(PinSerializer(pin).data)


class PinDeclineView(APIView):
    """Paged driver declines → reservation released, pin back to `active`."""

    permission_classes = [IsDriverRole]
    serializer_class = PinSerializer

    @extend_schema(request=None, responses=PinSerializer, tags=["drivers"])
    def post(self, request, pin_id):
        profile, err = _driver_profile_or_400(request)
        if err:
            return err
        pin, err = _live_pin_or_400(pin_id)
        if err:
            return err
        if not EmergencyPage.objects.filter(
            pin=pin, driver=profile, outcome=EmergencyPage.Outcome.PAGED
        ).exists():
            return Response(
                {"detail": "No emergency page for this driver."},
                status=status.HTTP_403_FORBIDDEN,
            )
        release_reservation(pin, EmergencyPage.Outcome.DECLINED, driver=profile)
        pin.refresh_from_db()
        from realtime.broadcast import publish_demand

        publish_demand(pin.junction_id)
        return Response(PinSerializer(pin).data)


class PinCompleteView(APIView):
    """Pickup-code completion. Reserved pins: holder only. Active pins:
    visibility-set members only. Wrong codes rate-limited per pin."""

    permission_classes = [IsDriverRole]
    serializer_class = PinCompleteSerializer

    @extend_schema(
        request=PinCompleteSerializer, responses=PinSerializer, tags=["drivers"]
    )
    def post(self, request, pin_id):
        import hmac

        from django.conf import settings
        from django.core.cache import cache

        from .visibility import eligible_for_pin

        profile, err = _driver_profile_or_400(request)
        if err:
            return err
        pin, err = _live_pin_or_400(pin_id)
        if err:
            return err
        code = request.data.get("pickup_code", "")

        if pin.status == Pin.Status.RESERVED:
            if pin.reserved_by_id != profile.id:
                return Response(
                    {"detail": "Pin is reserved by another driver."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        elif not eligible_for_pin(profile, pin):
            return Response(
                {"detail": "Pin is not visible to this driver."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cache_key = f"pin_attempts:{pin.id}"
        attempts = cache.get(cache_key, 0)
        if attempts >= settings.PICKUP_CODE_ATTEMPTS:
            return Response(
                {"detail": "Too many attempts. Ask the passenger again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if not hmac.compare_digest(str(pin.pickup_code), str(code)):
            cache.set(cache_key, attempts + 1, timeout=600)
            return Response(
                {"detail": "Wrong pickup code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            now = timezone.now()
            pin.status = Pin.Status.COMPLETED
            pin.completed_by = profile
            pin.completed_at = now
            pin.reserved_by = None
            pin.reserved_at = None
            pin.reservation_expires_at = None
            pin.save()
            try:
                tip = pin.tip
            except Pin.tip.RelatedObjectDoesNotExist:
                tip = None
            if tip is not None and tip.status == "paid":
                tip.claimed_by_driver = profile
                tip.save(update_fields=["claimed_by_driver"])
        cache.delete(cache_key)
        from realtime.broadcast import publish_demand, publish_pin_event

        publish_demand(pin.junction_id)
        publish_pin_event(pin.junction_id, "completed", pin.id)
        return Response(PinSerializer(pin).data)
