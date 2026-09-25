from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OTPVerification, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("created_at",)
    list_display = ("phone_number", "email", "role", "is_verified", "is_staff")
    list_filter = ("role", "is_verified", "is_staff")
    search_fields = ("phone_number", "email")
    fieldsets = (
        (None, {"fields": ("phone_number", "email", "password")}),
        ("Status", {"fields": ("role", "is_verified", "is_active", "is_staff")}),
        ("Permissions", {"fields": ("is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "fields": (
                    "phone_number",
                    "email",
                    "password1",
                    "password2",
                    "role",
                    "is_verified",
                )
            },
        ),
    )


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ("email", "is_used", "attempt_count", "created_at", "expires_at")
    list_filter = ("is_used",)
    search_fields = ("email",)
