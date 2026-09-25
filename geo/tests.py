from datetime import date, time, datetime, timezone as dt_timezone
from decimal import Decimal
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
