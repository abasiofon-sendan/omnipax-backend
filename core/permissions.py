from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """Spec §9: admin endpoints require role=admin AND staff permission."""

    message = "Admin access required."

    def has_permission(self, request, view):
        user = request.user
        return (
            bool(user and user.is_authenticated)
            and user.is_staff
            and getattr(user, "role", None) == "admin"
        )
