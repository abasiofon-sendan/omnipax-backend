import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from drivers.models import DriverLocation, DriverProfile
from geo.models import Corridor, Junction
from rides.models import EmergencyPage, Pin
from .models import Tip

WEBHOOK_SECRET = "test-webhook-secret"


def make_rider():
    return User.objects.create_user(
        phone_number="+2348011111111",
        email="rider@example.com",
        password="testpass1",
        is_verified=True,
    )


def make_geo():
    corridor = Corridor.objects.create(name="Oron Road")
    junction = Junction.objects.create(
        name="Ibom Plaza", corridor=corridor,
        latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
    )
    return corridor, junction


def make_driver(phone, email, corridor, lat, lng, vehicle="keke"):
    user = User.objects.create_user(
        phone_number=phone, email=email, password="testpass1",
        role=User.Role.DRIVER, is_verified=True,
    )
    profile = DriverProfile.objects.create(
        user=user,
        registration_id=f"REG-{phone[-4:]}",
        vehicle_type=vehicle,
        plate_number="TEST",
        approved_corridor=corridor,
        verification_status=DriverProfile.VerificationStatus.VERIFIED,
        is_online=True,
    )
    DriverLocation.objects.create(
        driver=profile, latitude=lat, longitude=lng, recorded_at=timezone.now()
    )
    return profile


def make_pin(rider, corridor, junction, device="dev-1"):
    return Pin.objects.create(
        passenger=rider, device_id=device,
        raw_latitude="5.0421", raw_longitude="7.9121",
        junction=junction, corridor=corridor, vehicle_type="keke",
        pickup_code="1234",
        expires_at=timezone.now() + timedelta(minutes=6),
    )


def signed_post(client, body):
    raw = json.dumps(body).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/api/payments/webhook/bachs/",
        data=raw,
        content_type="application/json",
        HTTP_X_BACHS_SIGNATURE=sig,
    )


@override_settings(BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)
class TipFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.rider = make_rider()
        self.client.force_authenticate(user=self.rider)
        self.corridor, self.junction = make_geo()
        self.near = make_driver(
            "+2348100000001", "near@example.com", self.corridor, "5.0425", "7.9125"
        )
        self.far = make_driver(
            "+2348100000002", "far@example.com", self.corridor, "5.1000", "8.0000"
        )
        self.pin = make_pin(self.rider, self.corridor, self.junction)

    def initiate(self, pin_id=None, amount=None):
        payload = {}
        if amount is not None:
            payload["amount"] = amount
        return self.client.post(
            f"/api/pins/{pin_id or self.pin.id}/tip/", payload, format="json"
        )

    def test_initiate_creates_pending_tip(self):
        res = self.initiate(amount="250.00")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "pending")
        self.assertIn("redirect_url", res.data)
        tip = Tip.objects.get(pin=self.pin)
        self.assertEqual(str(tip.amount), "250.00")
        self.assertTrue(tip.bachs_reference.startswith("sandbox-"))

    def test_webhook_confirms_and_pages_nearest(self):
        self.initiate()
        tip = Tip.objects.get(pin=self.pin)
        res = signed_post(self.client, {"reference": tip.bachs_reference, "status": "paid"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["processed"])
        self.assertEqual(res.data["paged_driver"], str(self.near.id))
        tip.refresh_from_db()
        self.pin.refresh_from_db()
        self.assertEqual(tip.status, "paid")
        self.assertEqual(self.pin.priority, "priority")
        self.assertIsNotNone(self.pin.reservation_expires_at)
        page = EmergencyPage.objects.get(pin=self.pin)
        self.assertEqual(page.driver, self.near)
        status_res = self.client.get(f"/api/pins/{self.pin.id}/status/")
        self.assertEqual(status_res.data["emergency_state"], "paged")

    def test_webhook_idempotent(self):
        self.initiate()
        tip = Tip.objects.get(pin=self.pin)
        body = {"reference": tip.bachs_reference, "status": "paid"}
        first = signed_post(self.client, body)
        second = signed_post(self.client, body)
        self.assertTrue(first.data["processed"])
        self.assertFalse(second.data["processed"])
        self.assertEqual(EmergencyPage.objects.filter(pin=self.pin).count(), 1)

    def test_webhook_bad_signature_rejected(self):
        res = self.client.post(
            "/api/payments/webhook/bachs/",
            data=json.dumps({"reference": "x"}).encode(),
            content_type="application/json",
            HTTP_X_BACHS_SIGNATURE="bogus",
        )
        self.assertEqual(res.status_code, 403)

    def test_webhook_unknown_reference(self):
        res = signed_post(self.client, {"reference": "nope", "status": "paid"})
        self.assertEqual(res.status_code, 404)

    def test_no_eligible_driver_reports_no_driver(self):
        DriverProfile.objects.all().update(is_online=False)
        self.initiate()
        tip = Tip.objects.get(pin=self.pin)
        res = signed_post(self.client, {"reference": tip.bachs_reference, "status": "paid"})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["paged_driver"])
        self.pin.refresh_from_db()
        self.assertEqual(self.pin.priority, "priority")
        status_res = self.client.get(f"/api/pins/{self.pin.id}/status/")
        self.assertEqual(status_res.data["emergency_state"], "no_driver")

    def test_repage_after_decline_skips_paged_driver(self):
        self.initiate()
        tip = Tip.objects.get(pin=self.pin)
        signed_post(self.client, {"reference": tip.bachs_reference, "status": "paid"})
        first_page = EmergencyPage.objects.get(pin=self.pin)
        # simulate a decline (decline endpoint lands in step 9)
        first_page.outcome = EmergencyPage.Outcome.DECLINED
        first_page.resolved_at = timezone.now()
        first_page.save()

        res = self.initiate()
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data.get("repaged"))
        self.assertEqual(Tip.objects.filter(pin=self.pin).count(), 1)
        second_page = EmergencyPage.objects.exclude(id=first_page.id).get(pin=self.pin)
        self.assertEqual(second_page.driver, self.far)

    def test_tip_on_dead_pin_rejected(self):
        self.pin.status = Pin.Status.EXPIRED
        self.pin.save(update_fields=["status"])
        res = self.initiate()
        self.assertEqual(res.status_code, 400)


class WebhookUnconfiguredTests(TestCase):
    @override_settings(BACHS_WEBHOOK_SECRET="")
    def test_rejected_when_no_secret(self):
        client = APIClient()
        res = client.post(
            "/api/payments/webhook/bachs/",
            {"reference": "x"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
