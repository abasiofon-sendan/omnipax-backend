import uuid

from django.conf import settings
from django.db import models

from core.choices import VehicleType
from geo.models import Corridor


class DriverProfile(models.Model):
    """Driver identity + approval state. Paging and completion (steps 8-9)
    only ever select verified, online profiles."""

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="driver_profile"
    )
    registration_id = models.CharField(max_length=64, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices)
    plate_number = models.CharField(max_length=32)
    approved_corridor = models.ForeignKey(
        Corridor, on_delete=models.PROTECT, related_name="drivers"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    is_online = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Driver {self.registration_id} ({self.verification_status})"

    @property
    def is_verified(self):
        return self.verification_status == self.VerificationStatus.VERIFIED


class DriverLocation(models.Model):
    """Current location only — one row per driver, upserted on every heartbeat.
    No history table for MVP. Locations older than
    settings.DRIVER_LOCATION_STALE_SECONDS are stale and excluded everywhere."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.OneToOneField(
        DriverProfile, on_delete=models.CASCADE, related_name="location"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_meters = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()

    def __str__(self):
        return f"Location of {self.driver_id} @ {self.recorded_at}"
