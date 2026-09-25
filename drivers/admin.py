from django.contrib import admin

from .models import DriverLocation, DriverProfile


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = (
        "registration_id",
        "user",
        "vehicle_type",
        "verification_status",
        "is_online",
    )
    list_filter = ("verification_status", "is_online", "vehicle_type")
    search_fields = ("registration_id", "plate_number")


@admin.register(DriverLocation)
class DriverLocationAdmin(admin.ModelAdmin):
    list_display = ("driver", "latitude", "longitude", "recorded_at")
