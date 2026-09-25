from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from geo.models import Corridor, Junction, RestrictedZone
from .models import Pin


def make_user(phone="+2348011111111", email="rider@example.com"):
    return User.objects.create_user(
        phone_number=phone, email=email, password="testpass1", is_verified=True
    )


def make_corridor(name="Oron Road"):
    return Corridor.objects.create(name=name)


def make_junction(corridor, name="Ibom Plaza", lat="5.0420", lng="7.9120"):
    return Junction.objects.create(
        name=name,
        corridor=corridor,
        latitude=Decimal(lat),
        longitude=Decimal(lng),
    )


def pin_payload(corridor, lat="5.0421", lng="7.9121", device="dev-1"):
    return {
        "latitude": lat,
        "longitude": lng,
        "corridor_id": str(corridor.id),
        "vehicle_type": "keke",
        "direction": "towards Tropicana",
        "device_id": device,
    }


class PinFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.corridor = make_corridor()
        self.junction = make_junction(self.corridor)

    def test_create_pin_resolves_junction(self):
        res = self.client.post("/api/pins/", pin_payload(self.corridor), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(str(res.data["junction"]), str(self.junction.id))
        self.assertEqual(res.data["status"], "active")
        self.assertEqual(res.data["priority"], "standard")
        self.assertRegex(res.data["pickup_code"], r"^\d{4}$")

    def test_duplicate_device_rejected(self):
        self.assertEqual(
            self.client.post("/api/pins/", pin_payload(self.corridor), format="json").status_code,
            201,
        )
        res = self.client.post("/api/pins/", pin_payload(self.corridor), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "duplicate_pin")

    def test_second_device_allowed(self):
        self.client.post("/api/pins/", pin_payload(self.corridor), format="json")
        res = self.client.post(
            "/api/pins/", pin_payload(self.corridor, device="dev-2"), format="json"
        )
        self.assertEqual(res.status_code, 201)

    def test_out_of_radius_rejected(self):
        # In-bbox but ~4km from the junction: passes bbox, fails radius.
        res = self.client.post(
            "/api/pins/", pin_payload(self.corridor, lat="5.0600", lng="7.9500"),
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "out_of_radius")

    def test_restricted_zone_blocked(self):
        RestrictedZone.objects.create(
            name="No Keke",
            junction=self.junction,
            coordinates={"center": [5.0420, 7.9120], "radius_m": 500},
            restriction_type="full_closure",
            effective_date=date(2026, 1, 1),
            reason="Ministry order",
        )
        res = self.client.post("/api/pins/", pin_payload(self.corridor), format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data["code"], "restricted_zone")

    def test_corridor_mismatch_rejected(self):
        other = make_corridor("Aka Road")
        res = self.client.post("/api/pins/", pin_payload(other), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "junction_corridor_mismatch")

    def test_active_cancel_status(self):
        created = self.client.post(
            "/api/pins/", pin_payload(self.corridor), format="json"
        ).data
        pin_id = created["id"]

        res = self.client.get("/api/pins/active/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["id"], pin_id)

        res = self.client.get(f"/api/pins/{pin_id}/status/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["emergency_state"], "none")

        res = self.client.post(f"/api/pins/{pin_id}/cancel/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "cancelled")
        self.assertEqual(self.client.get("/api/pins/active/").status_code, 404)

    def test_cannot_cancel_twice_or_others_pin(self):
        pin_id = self.client.post(
            "/api/pins/", pin_payload(self.corridor), format="json"
        ).data["id"]
        self.client.post(f"/api/pins/{pin_id}/cancel/")
        res = self.client.post(f"/api/pins/{pin_id}/cancel/")
        self.assertEqual(res.status_code, 400)

        other = make_user("+2348022222222", "other@example.com")
        self.client.force_authenticate(user=other)
        res = self.client.post(f"/api/pins/{pin_id}/cancel/")
        self.assertEqual(res.status_code, 404)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        res = self.client.post("/api/pins/", pin_payload(self.corridor), format="json")
        self.assertEqual(res.status_code, 401)


class ExpirePinsTests(TestCase):
    def setUp(self):
        from django.utils import timezone

        self.user = make_user()
        self.corridor = make_corridor()
        self.junction = make_junction(self.corridor)
        self.now = timezone.now()

    def make_pin(self, device, status="active", expires_delta=None,
                 reservation_delta=None):
        from datetime import timedelta

        from drivers.models import DriverProfile

        pin = Pin.objects.create(
            passenger=self.user,
            device_id=device,
            raw_latitude="5.0421",
            raw_longitude="7.9121",
            junction=self.junction,
            corridor=self.corridor,
            vehicle_type="keke",
            status=status,
            pickup_code="1234",
            expires_at=self.now + (expires_delta or timedelta(minutes=6)),
        )
        if status == "reserved":
            driver_user = make_user("+2348099999999", "drv@example.com")
            profile = DriverProfile.objects.create(
                user=driver_user,
                registration_id="REG-1",
                vehicle_type="keke",
                plate_number="X",
                approved_corridor=self.corridor,
            )
            pin.reserved_by = profile
            pin.reserved_at = self.now - timedelta(minutes=5)
            pin.reservation_expires_at = self.now + (
                reservation_delta or timedelta(seconds=90)
            )
            pin.save()
        return pin

    def test_expires_overdue_active_pins_only(self):
        from datetime import timedelta

        from .tasks import expire_pins

        live = self.make_pin("d-live")
        stale = self.make_pin("d-stale", expires_delta=timedelta(minutes=-1))
        result = expire_pins()
        self.assertEqual(result, {"expired": 1, "released": 0})
        live.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(live.status, "active")
        self.assertEqual(stale.status, "expired")

    def test_releases_overdue_reservation(self):
        from datetime import timedelta

        from .models import EmergencyPage
        from .tasks import expire_pins

        pin = self.make_pin(
            "d-res", status="reserved", reservation_delta=timedelta(seconds=-10)
        )
        page = EmergencyPage.objects.create(
            pin=pin, driver=pin.reserved_by, outcome="paged"
        )
        result = expire_pins()
        self.assertEqual(result, {"expired": 0, "released": 1})
        pin.refresh_from_db()
        page.refresh_from_db()
        self.assertEqual(pin.status, "active")
        self.assertIsNone(pin.reserved_by)
        self.assertEqual(page.outcome, "expired")

    def test_reserved_pin_past_ttl_expires(self):
        from datetime import timedelta

        from .tasks import expire_pins

        pin = self.make_pin(
            "d-res2",
            status="reserved",
            expires_delta=timedelta(minutes=-1),
            reservation_delta=timedelta(seconds=-10),
        )
        expire_pins()
        pin.refresh_from_db()
        self.assertEqual(pin.status, "expired")
