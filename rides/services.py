"""Pin creation flow (design spec §7 rule 1)."""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.codes import generate_pickup_code
from core.geo_utils import find_blocking_zone, inside_bbox, resolve_junction
from drivers.visibility import assign_visibility
from geo.models import Corridor, Junction, RestrictedZone

from .models import Pin


def create_pin(*, passenger, device_id, latitude, longitude, corridor_id,
               vehicle_type, direction=""):
    """Validate and create an active standard pin. Raises ValidationError with
    a machine-readable code in `e.code`."""
    lat, lng = float(latitude), float(longitude)

    if not inside_bbox(lat, lng):
        raise ValidationError("Coordinates outside service area.", code="out_of_area")

    try:
        corridor = Corridor.objects.get(id=corridor_id, is_active=True)
    except (Corridor.DoesNotExist, ValueError, TypeError):
        raise ValidationError("Unknown or inactive corridor.", code="bad_corridor")

    if Pin.objects.filter(
        passenger=passenger, device_id=device_id, status__in=Pin.LIVE_STATUSES
    ).exists():
        raise ValidationError(
            "This device already has an active pin.", code="duplicate_pin"
        )

    junction, _ = resolve_junction(
        lat, lng, Junction.objects.filter(is_active=True)
    )
    if junction is None:
        raise ValidationError(
            "No pickup junction within range of your location.",
            code="out_of_radius",
        )
    if junction.corridor_id != corridor.id:
        raise ValidationError(
            "Nearest junction is not on the selected corridor.",
            code="junction_corridor_mismatch",
        )

    zone = find_blocking_zone(
        lat, lng, RestrictedZone.objects.filter(is_active=True)
    )
    if zone is not None:
        raise ValidationError(
            f"Pickup blocked here: {zone.reason}", code="restricted_zone"
        )

    existing_codes = Pin.objects.filter(status__in=Pin.LIVE_STATUSES).values_list(
        "pickup_code", flat=True
    )
    now = timezone.now()
    pin = Pin.objects.create(
        passenger=passenger,
        device_id=device_id,
        raw_latitude=latitude,
        raw_longitude=longitude,
        junction=junction,
        corridor=corridor,
        direction=direction,
        vehicle_type=vehicle_type,
        status=Pin.Status.ACTIVE,
        priority=Pin.Priority.STANDARD,
        pickup_code=generate_pickup_code(existing_codes),
        expires_at=now + timedelta(minutes=settings.PIN_TTL_MINUTES),
    )
    # Persist the alert/eligibility set (push delivery lands in step 10;
    # polling over these rows works from now).
    assign_visibility(pin)
    from realtime.broadcast import publish_demand

    publish_demand(pin.junction_id)
    return pin


def release_reservation(pin, outcome, driver=None):
    """Release a reservation back to `active` (decline/timeout path). Shared by
    the decline endpoint (step 9) and the expiry sweep (step 7)."""
    from .models import EmergencyPage

    now = timezone.now()
    holder = driver or pin.reserved_by
    if holder is not None:
        EmergencyPage.objects.filter(
            pin=pin, driver=holder, outcome=EmergencyPage.Outcome.PAGED
        ).update(outcome=outcome, resolved_at=now)
    pin.status = Pin.Status.ACTIVE
    pin.reserved_by = None
    pin.reserved_at = None
    pin.reservation_expires_at = None
    pin.save(
        update_fields=[
            "status",
            "reserved_by",
            "reserved_at",
            "reservation_expires_at",
        ]
    )
    return pin
