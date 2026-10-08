from datetime import date, time, datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
import re

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core.geo_utils import (
    find_blocking_zone,
    haversine_m,
    inside_bbox,
    resolve_junction,
)
from .models import Corridor, Junction, RestrictedZone


def make_corridor(name="Oron Road"):
    return Corridor.objects.create(name=name)


def make_junction(corridor, name, lat, lng):
    return Junction.objects.create(
        name=name,
        corridor=corridor,
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lng)),
    )


class GeoUtilsTests(TestCase):
    def test_haversine_zero_and_known_distance(self):
        self.assertAlmostEqual(haversine_m(5.0, 7.9, 5.0, 7.9), 0.0)
        # 1 degree of longitude at the equator ≈ 111.2 km
        self.assertAlmostEqual(haversine_m(0.0, 0.0, 0.0, 1.0), 111195, delta=200)

    def test_inside_bbox(self):
        self.assertTrue(inside_bbox(5.0, 7.9))
        self.assertFalse(inside_bbox(0.0, 0.0))

    def test_resolve_nearest_junction(self):
        corridor = make_corridor()
        plaza = make_junction(corridor, "Ibom Plaza", 5.0420, 7.9120)
        make_junction(corridor, "Far Junction", 5.1000, 8.0000)
        junction, dist = resolve_junction(
            5.0421, 7.9121, Junction.objects.filter(is_active=True)
        )
        self.assertEqual(junction, plaza)
        self.assertLess(dist, 300)

    def test_resolve_rejects_out_of_radius(self):
        corridor = make_corridor()
        make_junction(corridor, "Ibom Plaza", 5.0420, 7.9120)
        junction, _ = resolve_junction(
            6.0000, 9.0000, Junction.objects.filter(is_active=True)
        )
        self.assertIsNone(junction)

    def test_full_closure_blocks_inside_only(self):
        corridor = make_corridor()
        junction = make_junction(corridor, "Ibom Plaza", 5.0420, 7.9120)
        zone = RestrictedZone.objects.create(
            name="No Keke",
            junction=junction,
            coordinates={"center": [5.0420, 7.9120], "radius_m": 200},
            restriction_type="full_closure",
            effective_date=date(2026, 1, 1),
            reason="Ministry order",
        )
        zones = RestrictedZone.objects.filter(is_active=True)
        self.assertEqual(find_blocking_zone(5.0421, 7.9121, zones), zone)
        self.assertIsNone(find_blocking_zone(5.0600, 7.9500, zones))

    def test_time_window_blocks_only_in_hours(self):
        corridor = make_corridor()
        make_junction(corridor, "Ibom Plaza", 5.0420, 7.9120)
        RestrictedZone.objects.create(
            name="Morning closure",
            coordinates={"center": [5.0420, 7.9120], "radius_m": 500},
            restriction_type="time_window",
            start_time=time(7, 0),
            end_time=time(9, 0),
            effective_date=date(2026, 1, 1),
            reason="Rush hour",
        )
        zones = RestrictedZone.objects.filter(is_active=True)
        inside = datetime(2026, 9, 23, 8, 0, tzinfo=dt_timezone.utc)
        outside = datetime(2026, 9, 23, 12, 0, tzinfo=dt_timezone.utc)
        self.assertIsNotNone(find_blocking_zone(5.0421, 7.9121, zones, at=inside))
        self.assertIsNone(find_blocking_zone(5.0421, 7.9121, zones, at=outside))


class AdminCrudTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            phone_number="+2348000000001",
            email="admin@example.com",
            password="adminpass1",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.rider = User.objects.create_user(
            phone_number="+2348000000002",
            email="rider@example.com",
            password="riderpass1",
        )

    def auth(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
        )

    def test_admin_can_crud_corridors(self):
        self.auth(self.admin)
        res = self.client.post(
            "/api/admin/corridors/", {"name": "Oron Road"}, format="json"
        )
        self.assertEqual(res.status_code, 201)
        res = self.client.get("/api/admin/corridors/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)

    def test_non_admin_forbidden(self):
        self.auth(self.rider)
        res = self.client.get("/api/admin/corridors/")
        self.assertEqual(res.status_code, 403)

    def test_anonymous_unauthorized(self):
        res = self.client.get("/api/admin/corridors/")
        self.assertEqual(res.status_code, 401)

    def test_time_window_requires_hours(self):
        self.auth(self.admin)
        res = self.client.post(
            "/api/admin/restricted-zones/",
            {
                "name": "Bad zone",
                "coordinates": {"center": [5.0, 7.9], "radius_m": 100},
                "restriction_type": "time_window",
                "effective_date": "2026-01-01",
                "reason": "test",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)


class SeedUyoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        out = StringIO()
        call_command("seed_uyo", stdout=out)
        cls.first_report = out.getvalue()

    def run_seed(self):
        out = StringIO()
        call_command("seed_uyo", stdout=out)
        return out.getvalue()

    @staticmethod
    def counts(report):
        return dict(
            (label, (int(created), int(updated)))
            for label, created, updated in re.findall(
                r"^(\w+): created=(\d+) updated=(\d+)", report, re.MULTILINE
            )
        )

    def test_seeds_expected_counts(self):
        self.assertEqual(Corridor.objects.count(), 3)
        self.assertEqual(Junction.objects.count(), 15)
        self.assertEqual(RestrictedZone.objects.count(), 4)

    def test_rerun_is_idempotent(self):
        report = self.run_seed()
        for label in ("corridors", "junctions", "zones"):
            self.assertEqual(self.counts(report)[label], (0, 0), label)

    def test_changed_coordinate_is_updated_in_place(self):
        plaza = Junction.objects.get(name="Ibom Plaza")
        junction_id = plaza.pk
        plaza.latitude = Decimal("5.039000")
        plaza.save(update_fields=["latitude"])

        report = self.run_seed()
        self.assertEqual(self.counts(report)["junctions"], (0, 1))
        plaza = Junction.objects.get(pk=junction_id)
        self.assertEqual(plaza.latitude, Decimal("5.038000"))

    def test_all_coordinates_inside_akwa_ibom_bbox(self):
        for junction in Junction.objects.all():
            self.assertTrue(
                inside_bbox(float(junction.latitude), float(junction.longitude)),
                f"{junction.name} outside bbox",
            )
        for zone in RestrictedZone.objects.all():
            lat, lng, radius = zone.coordinates["center"][0], zone.coordinates["center"][1], zone.coordinates["radius_m"]
            self.assertTrue(inside_bbox(lat, lng), f"{zone.name} outside bbox")
            self.assertGreater(radius, 0)

    def test_junctions_on_a_corridor_are_spaced_apart(self):
        for corridor in Corridor.objects.all():
            points = list(
                corridor.junctions.values_list("latitude", "longitude")
            )
            for i, a in enumerate(points):
                for b in points[i + 1 :]:
                    self.assertGreater(
                        haversine_m(float(a[0]), float(a[1]), float(b[0]), float(b[1])),
                        400,
                        f"{corridor.name} junctions too close",
                    )

    def test_zones_reference_existing_junctions(self):
        junction_ids = set(Junction.objects.values_list("id", flat=True))
        for zone in RestrictedZone.objects.all():
            self.assertIn(zone.junction_id, junction_ids, zone.name)

    def test_closure_blocks_and_inactive_zone_does_not(self):
        active = RestrictedZone.objects.filter(is_active=True)
        blocked = find_blocking_zone(5.0330, 7.9300, active)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.name, "Cover Road Culvert Works")
        # The paused Mbono Uyo zone must not block even on top of itself.
        self.assertIsNone(find_blocking_zone(5.0285, 7.8730, active))

    def test_unknown_zone_junction_reference_is_rejected(self):
        from django.core.management.base import CommandError

        from .management.commands import seed_uyo

        original = seed_uyo.ZONES
        seed_uyo.ZONES = [
            {**original[0], "name": "Bad ref", "junction": ("Nowhere Road", "Nope")}
        ]
        try:
            with self.assertRaises(CommandError):
                self.run_seed()
        finally:
            seed_uyo.ZONES = original
        self.assertEqual(RestrictedZone.objects.count(), 4)
