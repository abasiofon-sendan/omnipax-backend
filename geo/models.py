import uuid

from django.db import models


class Corridor(models.Model):
    """Major road (e.g. Oron Road)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Junction(models.Model):
    """Named pickup point on a corridor (e.g. Ibom Plaza)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    corridor = models.ForeignKey(
        Corridor, on_delete=models.PROTECT, related_name="junctions"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.corridor.name})"


class RestrictedZone(models.Model):
    """Closed road or time-windowed restriction, manually maintained for the demo.

    MVP simplification: `coordinates` is a center-point + radius circle,
    {"center": [lat, lng], "radius_m": N} — NOT full polygon geofencing.
    """

    class RestrictionType(models.TextChoices):
        FULL_CLOSURE = "full_closure", "Full closure"
        TIME_WINDOW = "time_window", "Time window"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    junction = models.ForeignKey(
        Junction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restricted_zones",
    )
    coordinates = models.JSONField(
        help_text='MVP shape: {"center": [lat, lng], "radius_m": N}'
    )
    restriction_type = models.CharField(
        max_length=20, choices=RestrictionType.choices
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    effective_date = models.DateField()
    reason = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.restriction_type})"
