"""Pure geo helpers. No GeoDjango: plain lat/lng + haversine in Python.

MVP simplification (documented, not full geofencing): restricted zones are
center-point + radius circles, tested with haversine distance. If GeoDjango ever
becomes available, only this module and the zone `coordinates` shape change.
"""

import math
from datetime import datetime

from django.conf import settings

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in meters between two lat/lng points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def inside_bbox(lat, lng):
    """Rough Akwa Ibom sanity check against garbage GPS data."""
    box = settings.AKWA_IBOM_BBOX
    return box["min_lat"] <= lat <= box["max_lat"] and box["min_lng"] <= lng <= box["max_lng"]


def nearest_junction(lat, lng, junctions):
    """Return (junction, distance_m) for the closest junction, or (None, None)."""
    best, best_dist = None, None
    for junction in junctions:
        dist = haversine_m(lat, lng, float(junction.latitude), float(junction.longitude))
        if best_dist is None or dist < best_dist:
            best, best_dist = junction, dist
    return best, best_dist


def resolve_junction(lat, lng, junctions, max_radius_m=None):
    """Nearest active junction within `max_radius_m`, else (None, nearest_dist).

    Callers reject the pin when the result is None.
    """
    limit = max_radius_m if max_radius_m is not None else settings.MAX_JUNCTION_RADIUS_METERS
    junction, dist = nearest_junction(lat, lng, junctions)
    if junction is None or dist > limit:
        return None, dist
    return junction, dist


def zone_center_radius(zone):
    """Extract (lat, lng, radius_m) from the MVP coordinates shape.

    MVP shape: {"center": [lat, lng], "radius_m": N}.
    """
    coords = zone.coordinates or {}
    center = coords.get("center", [None, None])
    return center[0], center[1], coords.get("radius_m", 0)


def zone_applies_at(zone, at):
    """Date/time gating. Assumes: applies on/after effective_date while active;
    time windows are same-day (start <= t <= end)."""
    if at.date() < zone.effective_date:
        return False
    if zone.restriction_type == "time_window":
        if zone.start_time is None or zone.end_time is None:
            return False
        now_t = at.time()
        return zone.start_time <= now_t <= zone.end_time
    return True  # full_closure


def find_blocking_zone(lat, lng, zones, at=None):
    """First active zone containing the point at time `at`, else None."""
    at = at or datetime.now().astimezone()
    for zone in zones:
        if not zone.is_active or not zone_applies_at(zone, at):
            continue
        clat, clng, radius = zone_center_radius(zone)
        if clat is None or not radius:
            continue
        if haversine_m(lat, lng, clat, clng) <= radius:
            return zone
    return None
