from rest_framework import serializers

from .models import EmergencyPage, Pin


class PinCreateSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    corridor_id = serializers.UUIDField()
    vehicle_type = serializers.ChoiceField(choices=["keke", "minibus"])
    direction = serializers.CharField(max_length=255, required=False, allow_blank=True)
    device_id = serializers.CharField(max_length=128)


class PinSerializer(serializers.ModelSerializer):
    junction_name = serializers.CharField(source="junction.name", read_only=True)
    corridor_name = serializers.CharField(source="corridor.name", read_only=True)
    emergency_state = serializers.SerializerMethodField()

    class Meta:
        model = Pin
        fields = [
            "id",
            "device_id",
            "raw_latitude",
            "raw_longitude",
            "junction",
            "junction_name",
            "corridor",
            "corridor_name",
            "direction",
            "vehicle_type",
            "status",
            "priority",
            "pickup_code",
            "created_at",
            "expires_at",
            "completed_at",
            "emergency_state",
        ]
        read_only_fields = fields

    def get_emergency_state(self, pin) -> str:
        # none: no paid tip. paged: awaiting driver accept. reserved: accepted.
        # released: pages declined/expired, re-pageable. no_driver: paid but no
        # eligible driver has ever qualified.
        if pin.status == Pin.Status.RESERVED:
            return "reserved"
        from payments.models import Tip

        if not Tip.objects.filter(pin=pin, status=Tip.Status.PAID).exists():
            return "none"
        latest = pin.pages.order_by("-created_at").first()
        if latest is None:
            return "no_driver"
        if latest.outcome == EmergencyPage.Outcome.PAGED:
            return "paged"
        return "released"
