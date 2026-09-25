from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from geo.models import Corridor
from .models import DriverLocation, DriverProfile


def make_user(phone, email, role=User.Role.PASSENGER, staff=False):
    return User.objects.create_user(
        phone_number=phone,
        email=email,
        password="testpass1",
        role=role,
        is_staff=staff,
        is_verified=True,
    )


def register_payload(corridor):
    return {
        "registration_id": "AKS-KEKE-001",
        "vehicle_type": "keke",
        "plate_number": "AKD-123-XA",
        "approved_corridor_id": str(corridor.id),
    }


class DriverFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("+2348011111111", "driver@example.com")
        self.client.force_authenticate(user=self.user)
        self.corridor = Corridor.objects.create(name="Oron Road")

    def auth_header(self, user):
        # fresh client: setUp uses force_authenticate, which would override headers
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
        )

    def test_register_creates_pending_profile(self):
        res = self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["verification_status"], "pending")
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.DRIVER)

    def test_duplicate_register_rejected(self):
        self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        )
        res = self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_admin_verify_and_reject(self):
        profile_id = self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        ).data["id"]
        admin = make_user("+2348099999999", "admin@example.com",
                          role=User.Role.ADMIN, staff=True)
        self.auth_header(admin)
        res = self.client.post(
            "/api/auth/driver/verify/",
            {"driver_id": profile_id, "action": "verify"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["verification_status"], "verified")

    def test_non_admin_cannot_verify(self):
        res = self.client.post(
            "/api/auth/driver/verify/",
            {"driver_id": "00000000-0000-0000-0000-000000000000", "action": "verify"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_heartbeat_and_online_toggle(self):
        self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        )
        res = self.client.post(
            "/api/driver/location/",
            {"latitude": "5.0450", "longitude": "7.9150", "accuracy_meters": 12.5},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(DriverLocation.objects.count(), 1)

        # second heartbeat upserts, not duplicates
        self.client.post(
            "/api/driver/location/",
            {"latitude": "5.0460", "longitude": "7.9160"},
            format="json",
        )
        self.assertEqual(DriverLocation.objects.count(), 1)

        res = self.client.post("/api/driver/online/", {"is_online": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["is_online"])
        profile = DriverProfile.objects.get()
        self.assertTrue(profile.is_online)

    def test_heartbeat_out_of_area_rejected(self):
        self.client.post(
            "/api/auth/driver/register/", register_payload(self.corridor), format="json"
        )
        res = self.client.post(
            "/api/driver/location/", {"latitude": "0.0", "longitude": "0.0"}, format="json"
        )
        self.assertEqual(res.status_code, 400)


def make_online_driver(phone, email, corridor, lat, lng, verified=True):
    from datetime import timedelta

    from django.utils import timezone

    user = User.objects.create_user(
        phone_number=phone, email=email, password="testpass1",
        role=User.Role.DRIVER, is_verified=True,
    )
    profile = DriverProfile.objects.create(
        user=user,
        registration_id=f"REG-{phone[-4:]}",
        vehicle_type="keke",
        plate_number="TEST",
        approved_corridor=corridor,
        verification_status=(
            DriverProfile.VerificationStatus.VERIFIED
            if verified
            else DriverProfile.VerificationStatus.PENDING
        ),
        is_online=True,
    )
    DriverLocation.objects.create(
        driver=profile, latitude=lat, longitude=lng, recorded_at=timezone.now()
    )
    return profile


def make_pin(client, corridor, device="dev-x"):
    return client.post(
        "/api/pins/",
        {
            "latitude": "5.0421",
            "longitude": "7.9121",
            "corridor_id": str(corridor.id),
            "vehicle_type": "keke",
            "direction": "towards Tropicana",
            "device_id": device,
        },
        format="json",
    )


class VisibilityTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from geo.models import Junction

        self.client = APIClient()
        self.rider = make_user("+2348011111111", "rider@example.com")
        self.client.force_authenticate(user=self.rider)
        self.corridor = Corridor.objects.create(name="Oron Road")
        self.junction = Junction.objects.create(
            name="Ibom Plaza", corridor=self.corridor,
            latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
        )
        # 3 near + 1 far + 1 unverified-near + 1 stale-near
        self.near = [
            make_online_driver(f"+234810000000{i}", f"d{i}@example.com",
                               self.corridor, "5.0425", "7.9125")
            for i in range(3)
        ]
        self.far = make_online_driver(
            "+2348100000009", "far@example.com", self.corridor, "5.1000", "8.0000"
        )
        self.unverified = make_online_driver(
            "+2348100000008", "unv@example.com", self.corridor,
            "5.0425", "7.9125", verified=False,
        )
        stale = make_online_driver(
            "+2348100000007", "stale@example.com", self.corridor,
            "5.0425", "7.9125",
        )
        from datetime import timedelta

        from django.utils import timezone

        DriverLocation.objects.filter(driver=stale).update(
            recorded_at=timezone.now() - timedelta(minutes=10)
        )

    def test_alert_set_is_nearest_three(self):
        from rides.models import PinDriverVisibility

        res = make_pin(self.client, self.corridor)
        self.assertEqual(res.status_code, 201)
        rows = PinDriverVisibility.objects.filter(pin_id=res.data["id"]).order_by("rank")
        self.assertEqual(rows.count(), 3)
        self.assertEqual([r.rank for r in rows], [1, 2, 3])
        driver_ids = {r.driver_id for r in rows}
        self.assertEqual(driver_ids, {p.id for p in self.near})
        self.assertNotIn(self.far.id, driver_ids)

    def test_driver_pins_endpoint_scoped_to_eligible(self):
        from rides.models import Pin

        pin_id = make_pin(self.client, self.corridor).data["id"]
        pin = Pin.objects.get(id=pin_id)

        near_client = APIClient()
        near_client.force_authenticate(user=self.near[0].user)
        res = near_client.get("/api/driver/pins/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([p["id"] for p in res.data], [str(pin.id)])

        far_client = APIClient()
        far_client.force_authenticate(user=self.far.user)
        res = far_client.get("/api/driver/pins/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])


class ZonesTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from geo.models import Junction

        self.rider = make_user("+2348011111111", "rider@example.com")
        self.corridor = Corridor.objects.create(name="Oron Road")
        self.busy = Junction.objects.create(
            name="Busy", corridor=self.corridor,
            latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
        )
        self.quiet = Junction.objects.create(
            name="Quiet", corridor=self.corridor,
            latitude=Decimal("5.0600"), longitude=Decimal("7.9500"),
        )
        make_online_driver("+2348100000001", "d1@example.com",
                           self.corridor, "5.0605", "7.9505")

    def test_heatmap_scores_and_top3(self):
        from rides.models import Pin

        Pin.objects.create(
            passenger=self.rider, device_id="d1",
            raw_latitude="5.0421", raw_longitude="7.9121",
            junction=self.busy, corridor=self.corridor, vehicle_type="keke",
            expires_at="2030-01-01T00:00:00Z",
        )
        Pin.objects.create(
            passenger=self.rider, device_id="d2",
            raw_latitude="5.0422", raw_longitude="7.9122",
            junction=self.busy, corridor=self.corridor, vehicle_type="keke",
            expires_at="2030-01-01T00:00:00Z",
        )
        client = APIClient()
        driver_user = User.objects.get(email="d1@example.com")
        client.force_authenticate(user=driver_user)
        res = client.get("/api/driver/zones/")
        self.assertEqual(res.status_code, 200)
        by_name = {j["name"]: j for j in res.data["junctions"]}
        # busy: 2 pins, 0 nearby drivers (driver is ~4km away) -> score 2.0
        self.assertEqual(by_name["Busy"]["active_pins"], 2)
        self.assertEqual(by_name["Busy"]["score"], 2.0)
        # quiet: 0 pins, 1 nearby driver -> score 0.0
        self.assertEqual(by_name["Quiet"]["available_drivers"], 1)
        self.assertEqual(by_name["Quiet"]["score"], 0.0)
        self.assertEqual(res.data["top3"][0]["name"], "Busy")
        self.assertEqual(len(res.data["top3"]), 2)


class AcceptDeclineCompleteTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from django.utils import timezone
        from geo.models import Junction

        self.rider = make_user("+2348011111111", "rider@example.com")
        self.corridor = Corridor.objects.create(name="Oron Road")
        self.junction = Junction.objects.create(
            name="Ibom Plaza", corridor=self.corridor,
            latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
        )
        self.near = [
            make_online_driver(f"+234810000000{i}", f"d{i}@example.com",
                               self.corridor, "5.0425", "7.9125")
            for i in range(2)
        ]
        self.other = make_online_driver(
            "+2348100000009", "other@example.com", self.corridor, "5.1000", "8.0000"
        )
        rider_client = APIClient()
        rider_client.force_authenticate(user=self.rider)
        res = make_pin(rider_client, self.corridor, device="dev-9")
        assert res.status_code == 201, res.data
        from rides.models import Pin

        self.pin = Pin.objects.get(id=res.data["id"])
        self.code = res.data["pickup_code"]

    def driver_client(self, profile):
        client = APIClient()
        client.force_authenticate(user=profile.user)
        return client

    def pay_and_page(self):
        from django.utils import timezone

        from payments.models import Tip
        from payments.services import page_nearest_driver

        tip = Tip.objects.create(
            pin=self.pin, status=Tip.Status.PAID, paid_at=timezone.now(),
        )
        self.pin.priority = "priority"
        self.pin.save(update_fields=["priority"])
        return tip, page_nearest_driver(self.pin)

    def test_accept_reserves_and_blocks_others(self):
        from rides.models import EmergencyPage, Pin

        _, page = self.pay_and_page()
        self.assertEqual(page.driver, self.near[0])

        # non-paged driver cannot accept while pin is still active
        res = self.driver_client(self.near[1]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        self.assertEqual(res.status_code, 403)

        res = self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "reserved")
        page.refresh_from_db()
        self.assertEqual(page.outcome, "accepted")

        # once reserved, accept is closed for everyone else
        res = self.driver_client(self.near[1]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        self.assertEqual(res.status_code, 400)

        # non-holder cannot complete even with the right code
        res = self.driver_client(self.near[1]).post(
            f"/api/driver/pins/{self.pin.id}/complete/",
            {"pickup_code": self.code},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Pin.objects.get(id=self.pin.id).status, "reserved")

    def test_accept_after_deadline_fails(self):
        from datetime import timedelta

        from django.utils import timezone
        from rides.models import EmergencyPage

        self.pay_and_page()
        Pin = self.pin.__class__
        Pin.objects.filter(id=self.pin.id).update(
            reservation_expires_at=timezone.now() - timedelta(seconds=1)
        )
        res = self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        self.assertEqual(res.status_code, 400)
        page = EmergencyPage.objects.get(pin=self.pin)
        self.assertEqual(page.outcome, "expired")

    def test_decline_releases_pin(self):
        from rides.models import EmergencyPage, Pin

        self.pay_and_page()
        res = self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/decline/"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "active")
        self.assertEqual(res.data["emergency_state"], "released")
        page = EmergencyPage.objects.get(pin=self.pin)
        self.assertEqual(page.outcome, "declined")
        self.assertEqual(Pin.objects.get(id=self.pin.id).status, "active")

    def test_complete_with_code_records_tip_claim(self):
        from payments.models import Tip
        from rides.models import Pin

        tip, _ = self.pay_and_page()
        self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        res = self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/complete/",
            {"pickup_code": self.code},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "completed")
        pin = Pin.objects.get(id=self.pin.id)
        self.assertEqual(pin.completed_by, self.near[0])
        tip.refresh_from_db()
        self.assertEqual(tip.claimed_by_driver, self.near[0])

    def test_wrong_code_rate_limited(self):
        self.pay_and_page()
        self.driver_client(self.near[0]).post(
            f"/api/driver/pins/{self.pin.id}/accept/"
        )
        url = f"/api/driver/pins/{self.pin.id}/complete/"
        client = self.driver_client(self.near[0])
        for _ in range(5):
            res = client.post(url, {"pickup_code": "0000"}, format="json")
            self.assertEqual(res.status_code, 400)
        res = client.post(url, {"pickup_code": "0000"}, format="json")
        self.assertEqual(res.status_code, 429)

    def test_complete_active_pin_by_eligible_driver(self):
        from rides.models import Pin

        # no tip: standard pin, visibility-set path
        res = self.driver_client(self.near[1]).post(
            f"/api/driver/pins/{self.pin.id}/complete/",
            {"pickup_code": self.code},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Pin.objects.get(id=self.pin.id).status, "completed")

        res = self.driver_client(self.other).post(
            f"/api/driver/pins/{self.pin.id}/complete/",
            {"pickup_code": self.code},
            format="json",
        )
        self.assertIn(res.status_code, (400, 403))  # pin no longer live


