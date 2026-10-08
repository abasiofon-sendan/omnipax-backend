"""Seed the pilot Uyo dataset: corridors, junctions and restricted zones.

Coordinates are APPROXIMATE Uyo lat/lng, good enough for the demo and all
inside the Akwa Ibom sanity bbox; operations can correct them later either here
or via the admin (the command upserts by name, so edits survive re-runs).

Re-running is safe: natural keys are corridor name, (corridor, junction name)
and zone name. Existing rows are updated in place, never re-created, so
manual admin tweaks to unrelated rows are left alone.
"""

from datetime import date, time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from geo.models import Corridor, Junction, RestrictedZone

# (corridor name, junction name) references used by zones below.
CORRIDORS = [
    {
        "name": "Oron Road",
        "description": "Main artery south-east from Ibom Plaza toward Odu Oron.",
        "junctions": [
            {"name": "Ibom Plaza", "latitude": "5.038000", "longitude": "7.921000"},
            {"name": "Cover Road Junction", "latitude": "5.033000", "longitude": "7.930000"},
            {"name": "Nwaniba Junction", "latitude": "5.026000", "longitude": "7.940000"},
            {"name": "Uyo Town Hall", "latitude": "5.018000", "longitude": "7.953000"},
            {"name": "Odu Oron", "latitude": "5.010000", "longitude": "7.970000"},
        ],
    },
    {
        "name": "Aka Road",
        "description": "North-west artery toward Ekpri Nsukara and Aka.",
        "junctions": [
            {"name": "Aka Road Junction", "latitude": "5.045000", "longitude": "7.915000"},
            {"name": "Shelter Afrik", "latitude": "5.053000", "longitude": "7.911000"},
            {"name": "Ekpri Nsukara", "latitude": "5.061000", "longitude": "7.906000"},
            {"name": "Imeette", "latitude": "5.070000", "longitude": "7.900000"},
            {"name": "Okuip Junction", "latitude": "5.079000", "longitude": "7.894000"},
        ],
    },
    {
        "name": "Ikot Ekpene Road",
        "description": "Western artery toward Abak and Ikot Ekpene.",
        "junctions": [
            {"name": "Ikot Ekpene Junction", "latitude": "5.036000", "longitude": "7.912000"},
            {"name": "Abak Road Turn-off", "latitude": "5.033500", "longitude": "7.899000"},
            {"name": "Mbanson Road", "latitude": "5.031000", "longitude": "7.886000"},
            {"name": "Mbono Uyo", "latitude": "5.028500", "longitude": "7.873000"},
            {"name": "Akwa Ibom Depot", "latitude": "5.026000", "longitude": "7.860000"},
        ],
    },
]

ZONES = [
    {
        "name": "Cover Road Culvert Works",
        "junction": ("Oron Road", "Cover Road Junction"),
        "coordinates": {"center": [5.0330, 7.9300], "radius_m": 250},
        "restriction_type": "full_closure",
        "start_time": None,
        "end_time": None,
        "effective_date": date(2026, 1, 1),
        "reason": "Culvert reconstruction - no pickups at Cover Road",
        "is_active": True,
    },
    {
        "name": "Ibom Plaza Peak Hours",
        "junction": ("Oron Road", "Ibom Plaza"),
        "coordinates": {"center": [5.0380, 7.9210], "radius_m": 200},
        "restriction_type": "time_window",
        "start_time": time(7, 0),
        "end_time": time(19, 0),
        "effective_date": date(2026, 1, 1),
        "reason": "Peak-hour traffic calming at Ibom Plaza",
        "is_active": True,
    },
    {
        "name": "Ekpri Nsukara Market Closure",
        "junction": ("Aka Road", "Ekpri Nsukara"),
        "coordinates": {"center": [5.0610, 7.9060], "radius_m": 300},
        "restriction_type": "full_closure",
        "start_time": None,
        "end_time": None,
        "effective_date": date(2026, 1, 1),
        "reason": "Market-day road closure",
        "is_active": True,
    },
    {
        "name": "Mbono Uyo Repair Works",
        "junction": ("Ikot Ekpene Road", "Mbono Uyo"),
        "coordinates": {"center": [5.0285, 7.8730], "radius_m": 250},
        "restriction_type": "full_closure",
        "start_time": None,
        "end_time": None,
        "effective_date": date(2026, 1, 1),
        "reason": "Drainage repairs - paused until funding resumes",
        "is_active": False,
    },
]

STATUS = ("created", "updated", "unchanged")


def _upsert(model, lookup, defaults):
    """Create the row if missing, otherwise update only the changed fields.

    Returns one of `created`, `updated`, `unchanged`.
    """
    obj = model.objects.filter(**lookup).first()
    if obj is None:
        model.objects.create(**lookup, **defaults)
        return "created"
    dirty = [field for field, value in defaults.items() if getattr(obj, field) != value]
    if not dirty:
        return "unchanged"
    for field in dirty:
        setattr(obj, field, defaults[field])
    obj.save(update_fields=dirty)
    return "updated"


class Command(BaseCommand):
    help = "Seed (upsert) pilot Uyo corridors, junctions and restricted zones."

    def handle(self, *args, **options):
        self._validate()

        report = {"corridors": [], "junctions": [], "zones": []}
        with transaction.atomic():
            for corridor_data in CORRIDORS:
                lookup = {"name": corridor_data["name"]}
                defaults = {
                    "description": corridor_data["description"],
                    "is_active": True,
                }
                report["corridors"].append(_upsert(Corridor, lookup, defaults))

                corridor = Corridor.objects.get(name=corridor_data["name"])
                for junction_data in corridor_data["junctions"]:
                    lookup = {
                        "name": junction_data["name"],
                        "corridor": corridor,
                    }
                    defaults = {
                        "latitude": Decimal(junction_data["latitude"]),
                        "longitude": Decimal(junction_data["longitude"]),
                        "is_active": True,
                    }
                    report["junctions"].append(
                        _upsert(Junction, lookup, defaults)
                    )

            for zone_data in ZONES:
                junction = Junction.objects.get(
                    name=zone_data["junction"][1],
                    corridor__name=zone_data["junction"][0],
                )
                lookup = {"name": zone_data["name"]}
                defaults = {
                    "junction": junction,
                    "coordinates": zone_data["coordinates"],
                    "restriction_type": zone_data["restriction_type"],
                    "start_time": zone_data["start_time"],
                    "end_time": zone_data["end_time"],
                    "effective_date": zone_data["effective_date"],
                    "reason": zone_data["reason"],
                    "is_active": zone_data["is_active"],
                }
                report["zones"].append(_upsert(RestrictedZone, lookup, defaults))

        for label, statuses in report.items():
            counts = {status: statuses.count(status) for status in STATUS}
            self.stdout.write(
                f"{label}: created={counts['created']} "
                f"updated={counts['updated']} unchanged={counts['unchanged']}"
            )

    @staticmethod
    def _validate():
        """Reject bad seed data before anything is written."""
        known = {
            (corridor["name"], junction["name"])
            for corridor in CORRIDORS
            for junction in corridor["junctions"]
        }
        types = {choice.value for choice in RestrictedZone.RestrictionType}
        for zone in ZONES:
            if zone["junction"] not in known:
                raise CommandError(
                    f'Zone "{zone["name"]}" references unknown junction '
                    f'"{zone["junction"][1]}" on "{zone["junction"][0]}".'
                )
            if zone["restriction_type"] not in types:
                raise CommandError(
                    f'Zone "{zone["name"]}" has invalid restriction_type '
                    f'"{zone["restriction_type"]}".'
                )
            if zone["restriction_type"] == "time_window" and not (
                zone["start_time"] and zone["end_time"]
            ):
                raise CommandError(
                    f'Zone "{zone["name"]}" is a time_window but has no hours.'
                )
