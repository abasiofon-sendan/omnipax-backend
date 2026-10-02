"""Alert/eligibility computation — Option C (design spec §7 rule 2).

Heat is public; the nearest-set rule decides who gets push alerts on new demand
and who may complete the pin. Standard pins alert the nearest
STANDARD_VISIBILITY_COUNT drivers; emergency pages (step 8) target one driver.
Only verified, online drivers with fresh locations are ever selected, so
completion stays fraud-resistant.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.geo_utils import haversine_m
from geo.models import Junction
from rides.models import Pin, PinDriverVisibility

from .models import DriverLocation, DriverProfile


def fresh_cutoff():
    return timezone.now() - timedelta(
        seconds=settings.DRIVER_LOCATION_STALE_SECONDS
    )


def _ranked_candidates(junction, corridor_id):
    """(profile, distance_m) sorted nearest-first for online + verified drivers
    with a fresh location. Drivers with no approved corridor are eligible
    everywhere; drivers with one are scoped to that corridor."""
    from django.db.models import Q

    candidates = []
    profiles = DriverProfile.objects.filter(
        Q(approved_corridor_id=corridor_id)
        | Q(approved_corridor__isnull=True),
        is_online=True,
        verification_status=DriverProfile.VerificationStatus.VERIFIED,
        location__recorded_at__gte=fresh_cutoff(),
    ).select_related("location")
    for profile in profiles:
        loc = profile.location
        dist = haversine_m(
            float(junction.latitude),
            float(junction.longitude),
            float(loc.latitude),
            float(loc.longitude),
        )
        candidates.append((profile, dist))
    candidates.sort(key=lambda item: item[1])
    return candidates


def assign_visibility(pin, count=None):
    """Persist the alert/eligibility set for a new pin. Returns the rows."""
    limit = count if count is not None else settings.STANDARD_VISIBILITY_COUNT
    rows = [
        PinDriverVisibility(
            pin=pin, driver=profile, distance_meters=dist, rank=index + 1
        )
        for index, (profile, dist) in enumerate(
            _ranked_candidates(pin.junction, pin.corridor_id)[:limit]
        )
    ]
    PinDriverVisibility.objects.bulk_create(rows)
    return rows


def eligible_for_pin(driver_profile, pin):
    """Mandatory completion-gate check (steps 6/9)."""
    return PinDriverVisibility.objects.filter(pin=pin, driver=driver_profile).exists()


def available_driver_count(junction):
    """Online + fresh drivers within ZONE_SCORE_PROXIMITY_METERS of a junction,
    regardless of corridor (spec §6.3 literal)."""
    radius = settings.ZONE_SCORE_PROXIMITY_METERS
    cutoff = fresh_cutoff()
    count = 0
    locations = DriverLocation.objects.filter(
        driver__is_online=True, recorded_at__gte=cutoff
    ).select_related("driver")
    for loc in locations:
        if (
            haversine_m(
                float(junction.latitude),
                float(junction.longitude),
                float(loc.latitude),
                float(loc.longitude),
            )
            <= radius
        ):
            count += 1
    return count


def junction_heatmap():
    """Full per-junction demand array + top 3 by score (spec §6.3)."""
    items = []
    junctions = Junction.objects.filter(is_active=True).select_related("corridor")
    for junction in junctions:
        pins = Pin.objects.filter(
            junction=junction, status=Pin.Status.ACTIVE
        ).count()
        drivers = available_driver_count(junction)
        items.append(
            {
                "junction_id": str(junction.id),
                "name": junction.name,
                "corridor_id": str(junction.corridor_id),
                "corridor": junction.corridor.name,
                "active_pins": pins,
                "available_drivers": drivers,
                "score": pins / max(drivers, 1),
            }
        )
    items.sort(key=lambda item: item["score"], reverse=True)
    return {"top3": items[:3], "junctions": items}
