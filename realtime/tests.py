"""Consumer tests run each scenario inside ONE event loop.

Rationale: InMemoryChannelLayer is built on bare asyncio queues, so publishes
sent from a different thread/loop than the consumer's waiter never arrive.
Driving connect + publish + receive from a single loop matches how channels
itself tests consumers.
"""

from decimal import Decimal

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from config.asgi import application
from drivers.models import DriverLocation, DriverProfile
from geo.models import Corridor, Junction


def make_driver_user(phone, email, role=User.Role.DRIVER):
    return User.objects.create_user(
        phone_number=phone, email=email, password="testpass1",
        role=role, is_verified=True,
    )


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class DriverConsumerTests(TestCase):
    def setUp(self):
        self.corridor = Corridor.objects.create(name="Oron Road")
        self.junction = Junction.objects.create(
            name="Ibom Plaza", corridor=self.corridor,
            latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
        )
        self.user = make_driver_user("+2348100000001", "d1@example.com")
        self.profile = DriverProfile.objects.create(
            user=self.user, registration_id="REG-1", vehicle_type="keke",
            plate_number="X", approved_corridor=self.corridor,
            verification_status=DriverProfile.VerificationStatus.VERIFIED,
            is_online=True,
        )
        DriverLocation.objects.create(
            driver=self.profile, latitude="5.0425", longitude="7.9125",
            recorded_at=timezone.now(),
        )
        self.token = str(RefreshToken.for_user(self.user).access_token)

    def run_scenario(self, scenario):
        async_to_sync(scenario)()

    def test_connect_and_receive_demand_delta(self):
        async def scenario():
            comm = WebsocketCommunicator(application, f"/ws/driver/?token={self.token}")
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            try:
                await get_channel_layer().group_send(
                    f"junction_{self.junction.id}",
                    {
                        "type": "demand.event",
                        "junction_id": str(self.junction.id),
                        "active_pins": 3,
                    },
                )
                message = await comm.receive_json_from(timeout=5)
                self.assertEqual(message["kind"], "demand")
                self.assertEqual(message["junction_id"], str(self.junction.id))
                self.assertEqual(message["active_pins"], 3)
            finally:
                await comm.disconnect()

        self.run_scenario(scenario)

    def test_invalid_token_rejected(self):
        async def scenario():
            comm = WebsocketCommunicator(application, "/ws/driver/?token=bogus")
            connected, _ = await comm.connect()
            self.assertFalse(connected)

        self.run_scenario(scenario)

    def test_passenger_rejected(self):
        rider = make_driver_user(
            "+2348099999999", "rider@example.com", role=User.Role.PASSENGER
        )
        rider_token = str(RefreshToken.for_user(rider).access_token)

        async def scenario():
            comm = WebsocketCommunicator(application, f"/ws/driver/?token={rider_token}")
            connected, _ = await comm.connect()
            self.assertFalse(connected)

        self.run_scenario(scenario)

    def test_page_reaches_only_paged_driver(self):
        other_user = make_driver_user("+2348100000002", "d2@example.com")
        DriverProfile.objects.create(
            user=other_user, registration_id="REG-2", vehicle_type="keke",
            plate_number="Y", approved_corridor=self.corridor,
            verification_status=DriverProfile.VerificationStatus.VERIFIED,
            is_online=True,
        )
        other_token = str(RefreshToken.for_user(other_user).access_token)

        async def scenario():
            comm1 = WebsocketCommunicator(
                application, f"/ws/driver/?token={self.token}"
            )
            comm2 = WebsocketCommunicator(
                application, f"/ws/driver/?token={other_token}"
            )
            ok1, _ = await comm1.connect()
            ok2, _ = await comm2.connect()
            self.assertTrue(ok1 and ok2)
            try:
                await get_channel_layer().group_send(
                    f"driver_{self.profile.id}",
                    {"type": "page.event", "pin_id": "p1", "junction": "Ibom Plaza"},
                )
                message = await comm1.receive_json_from(timeout=5)
                self.assertEqual(message["kind"], "emergency_page")
                self.assertEqual(message["pin_id"], "p1")
                self.assertTrue(await comm2.receive_nothing(timeout=0.5))
            finally:
                await comm1.disconnect()
                await comm2.disconnect()

        self.run_scenario(scenario)


class BroadcastHelperTests(TestCase):
    """Sync tests for event shapes/group names (no sockets involved)."""

    def test_publish_demand_counts_active_only(self):
        from datetime import timedelta

        from realtime import broadcast
        from rides.models import Pin

        corridor = Corridor.objects.create(name="Oron Road")
        junction = Junction.objects.create(
            name="P", corridor=corridor,
            latitude=Decimal("5.0420"), longitude=Decimal("7.9120"),
        )
        rider = make_driver_user("+2348011111111", "r@example.com",
                                 role=User.Role.PASSENGER)
        Pin.objects.create(
            passenger=rider, device_id="d1",
            raw_latitude="5.0421", raw_longitude="7.9121",
            junction=junction, corridor=corridor, vehicle_type="keke",
            pickup_code="1111",
            expires_at=timezone.now() + timedelta(minutes=6),
        )
        captured = {}
        real_publish = broadcast._publish
        broadcast._publish = lambda group, event: captured.update(
            group=group, event=event
        )
        try:
            broadcast.publish_demand(junction.id)
        finally:
            broadcast._publish = real_publish
        self.assertEqual(captured["group"], f"junction_{junction.id}")
        self.assertEqual(captured["event"]["type"], "demand.event")
        self.assertEqual(captured["event"]["active_pins"], 1)
