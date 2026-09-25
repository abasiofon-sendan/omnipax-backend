"""Demo data simulator (design spec build step 12).

Plays realistic pins + driver movement through the REAL ingestion paths
(`create_pin`, location upserts) for one pilot corridor, so the demo exercises
the actual pipeline — scoring, visibility, heatmap — instead of fixtures.

If the corridor has no junctions yet, clearly-marked DEMO junctions are seeded
so the command works out of the box; replace them with real junctions via the
admin before the actual demo.
"""

import random
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from drivers.models import DriverLocation, DriverProfile
from drivers.visibility import junction_heatmap
from geo.models import Corridor, Junction
from rides.services import create_pin

# Rough Uyo center used ONLY for auto-seeded demo junctions.
DEMO_CENTER = (5.0420, 7.9120)


class Command(BaseCommand):
    help = "Simulate passenger pins + driver movement for a pilot corridor."

    def add_arguments(self, parser):
        parser.add_argument("--corridor", default="Oron Road")
        parser.add_argument("--pins", type=int, default=8)
        parser.add_argument("--drivers", type=int, default=4)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, corridor, pins, drivers, seed, **options):
        rng = random.Random(seed)
        try:
            corridor_obj = Corridor.objects.get(name=corridor, is_active=True)
        except Corridor.DoesNotExist:
            raise CommandError(f'Active corridor "{corridor}" not found.')

        junctions = list(
            Junction.objects.filter(corridor=corridor_obj, is_active=True)
        )
        if not junctions:
            self.stdout.write(
                self.style.WARNING("No junctions — seeding DEMO junctions.")
            )
            for i, (dlat, dlng) in enumerate([(0, 0), (0.008, 0.006), (-0.007, 0.009)]):
                junctions.append(
                    Junction.objects.create(
                        name=f"Demo Junction {chr(65 + i)}",
                        corridor=corridor_obj,
                        latitude=Decimal(str(DEMO_CENTER[0] + dlat)),
                        longitude=Decimal(str(DEMO_CENTER[1] + dlng)),
                    )
                )

        profiles = []
        for i in range(drivers):
            user, _ = User.objects.get_or_create(
                phone_number=f"+2347000002{i:02d}",
                defaults={
                    "email": f"demo-driver-{i}@example.com",
                    "is_verified": True,
                    "role": User.Role.DRIVER,
                },
            )
            user.set_password("demopass1")
            user.save()
            profile, _ = DriverProfile.objects.get_or_create(
                user=user,
                defaults={
                    "registration_id": f"DEMO-{i:03d}",
                    "vehicle_type": "keke",
                    "plate_number": f"DEMO-{i:03d}",
                    "approved_corridor": corridor_obj,
                    "verification_status": DriverProfile.VerificationStatus.VERIFIED,
                    "is_online": True,
                },
            )
            profile.is_online = True
            profile.save(update_fields=["is_online"])
            profiles.append(profile)

        rider, _ = User.objects.get_or_create(
            phone_number="+234700000100",
            defaults={
                "email": "demo-rider@example.com",
                "is_verified": True,
            },
        )

        moved, created = 0, 0
        for profile in profiles:
            junction = rng.choice(junctions)
            DriverLocation.objects.update_or_create(
                driver=profile,
                defaults={
                    "latitude": self._jitter(rng, junction.latitude),
                    "longitude": self._jitter(rng, junction.longitude),
                    "recorded_at": timezone.now(),
                },
            )
            moved += 1

        for i in range(pins):
            junction = rng.choice(junctions)
            try:
                create_pin(
                    passenger=rider,
                    device_id=f"demo-device-{i}",
                    latitude=self._jitter(rng, junction.latitude),
                    longitude=self._jitter(rng, junction.longitude),
                    corridor_id=corridor_obj.id,
                    vehicle_type="keke",
                    direction="demo ride",
                )
                created += 1
            except ValidationError as exc:
                self.stdout.write(f"pin {i} skipped: {exc.messages[0]}")

        heat = junction_heatmap()
        self.stdout.write(f"moved {moved} drivers, created {created} pins")
        for item in heat["top3"]:
            self.stdout.write(
                f"  {item['name']}: {item['active_pins']} pins, "
                f"{item['available_drivers']} drivers, score {item['score']:.2f}"
            )

    @staticmethod
    def _jitter(rng, value):
        return Decimal(str(float(value) + rng.uniform(-0.002, 0.002)))
