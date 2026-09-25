from django.contrib import admin

from .models import Corridor, Junction, RestrictedZone


@admin.register(Corridor)
class CorridorAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Junction)
class JunctionAdmin(admin.ModelAdmin):
    list_display = ("name", "corridor", "latitude", "longitude", "is_active")
    list_filter = ("is_active", "corridor")
    search_fields = ("name",)


@admin.register(RestrictedZone)
class RestrictedZoneAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "restriction_type",
        "effective_date",
        "is_active",
    )
    list_filter = ("restriction_type", "is_active")
    search_fields = ("name", "reason")
