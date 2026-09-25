from django.test import TestCase
from rest_framework.test import APIClient

from drivers.models import DriverProfile
from geo.models import Corridor
from rides.models import Pin


class HealthTests(TestCase):
    def test_health_ok(self):
        res = APIClient().get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "ok")
        self.assertEqual(res.data["db"], "ok")


class SimulatorTests(TestCase):
    def test_simulate_corridor_seeds_and_plays(self):
        from django.core.management import call_command

        Corridor.objects.create(name="Oron Road")
        call_command("simulate_corridor", corridor="Oron Road", pins=4, drivers=2)
        self.assertEqual(DriverProfile.objects.count(), 2)
        self.assertGreaterEqual(Pin.objects.count(), 1)
        # rerun is tolerated (devices collide -> pins skipped, no crash)
        call_command("simulate_corridor", corridor="Oron Road", pins=4, drivers=2)
        self.assertEqual(DriverProfile.objects.count(), 2)

    def test_simulate_unknown_corridor_errors(self):
        from django.core.management import call_command, CommandError

        with self.assertRaises(CommandError):
            call_command("simulate_corridor", corridor="Nope Road")
