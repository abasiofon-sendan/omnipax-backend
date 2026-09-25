import uuid

from django.db import models

from rides.models import Pin


class Tip(models.Model):
    """Emergency payment (no escrow). One per pin. A `paid` tip pages the
    nearest eligible driver; claiming is bookkeeping only, NOT a transfer."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pin = models.OneToOneField(Pin, on_delete=models.CASCADE, related_name="tip")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default="100.00")
    currency = models.CharField(max_length=8, default="NGN")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    bachs_reference = models.CharField(max_length=128, unique=True, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    claimed_by_driver = models.ForeignKey(
        "drivers.DriverProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claimed_tips",
    )

    def __str__(self):
        return f"Tip {self.amount} {self.currency} ({self.status})"
