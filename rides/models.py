import uuid

from django.conf import settings
from django.db import models

from core.choices import VehicleType
from geo.models import Corridor, Junction


class Pin(models.Model):
    """Passenger demand signal, pooled by junction. Never shown to drivers
    individually — drivers see junction aggregates; the pin surfaces only at
    completion via the passenger-held pickup code."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RESERVED = "reserved", "Reserved"
        EXPIRED = "expired", "Expired"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        STANDARD = "standard", "Standard"
        PRIORITY = "priority", "Priority"

    # A device with an active OR reserved pin may not create another one.
    LIVE_STATUSES = (Status.ACTIVE, Status.RESERVED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pins"
    )
    device_id = models.CharField(max_length=128, db_index=True)
    raw_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    raw_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    junction = models.ForeignKey(
        Junction, on_delete=models.PROTECT, related_name="pins"
    )
    corridor = models.ForeignKey(
        Corridor, on_delete=models.PROTECT, related_name="pins"
    )
    direction = models.CharField(max_length=255, blank=True)
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.STANDARD
    )
    pickup_code = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    completed_by = models.ForeignKey(
        "drivers.DriverProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_pins",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    reserved_by = models.ForeignKey(
        "drivers.DriverProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserved_pins",
    )
    reserved_at = models.DateTimeField(null=True, blank=True)
    reservation_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pin {self.pickup_code} @ {self.junction.name} ({self.status})"

    @property
    def is_live(self):
        return self.status in self.LIVE_STATUSES


class EmergencyPage(models.Model):
    """One row per emergency page attempt. Re-pages skip already-paged drivers
    so a released pin can escalate without charging the passenger twice."""

    class Outcome(models.TextChoices):
        PAGED = "paged", "Paged"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pin = models.ForeignKey(Pin, on_delete=models.CASCADE, related_name="pages")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="pages"
    )
    outcome = models.CharField(
        max_length=20, choices=Outcome.choices, default=Outcome.PAGED, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Page {self.pin.pickup_code} -> {self.driver_id} ({self.outcome})"


class PinDriverVisibility(models.Model):
    """Alert/eligibility record: drivers notified of a pin's demand at creation
    and eligible to complete it. Computed live at alert time (build step 6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pin = models.ForeignKey(Pin, on_delete=models.CASCADE, related_name="visibility")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="visibility"
    )
    distance_meters = models.FloatField()
    rank = models.IntegerField()
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["pin", "driver"], name="unique_pin_driver")
        ]
