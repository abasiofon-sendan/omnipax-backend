from django.contrib import admin

from .models import EmergencyPage, Pin, PinDriverVisibility


@admin.register(Pin)
class PinAdmin(admin.ModelAdmin):
    list_display = (
        "pickup_code",
        "junction",
        "vehicle_type",
        "status",
        "priority",
        "created_at",
        "expires_at",
    )
    list_filter = ("status", "priority", "vehicle_type")
    search_fields = ("pickup_code", "device_id")


@admin.register(EmergencyPage)
class EmergencyPageAdmin(admin.ModelAdmin):
    list_display = ("pin", "driver", "outcome", "created_at", "resolved_at")
    list_filter = ("outcome",)


@admin.register(PinDriverVisibility)
class PinDriverVisibilityAdmin(admin.ModelAdmin):
    list_display = ("pin", "driver", "rank", "distance_meters", "assigned_at")
