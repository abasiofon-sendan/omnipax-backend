from django.db import models


class VehicleType(models.TextChoices):
    KEKE = "keke", "Keke Napep"
    MINIBUS = "minibus", "Mini-bus"
