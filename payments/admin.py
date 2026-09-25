from django.contrib import admin

from .models import Tip


@admin.register(Tip)
class TipAdmin(admin.ModelAdmin):
    list_display = (
        "pin",
        "amount",
        "currency",
        "status",
        "bachs_reference",
        "paid_at",
    )
    list_filter = ("status",)
