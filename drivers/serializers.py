from rest_framework import serializers

from .models import DriverLocation, DriverProfile


class DriverRegisterSerializer(serializers.Serializer):
    registration_id = serializers.CharField(max_length=64)
    vehicle_type = serializers.ChoiceField(choices=["keke", "minibus"])
    plate_number = serializers.CharField(max_length=32)
    approved_corridor_id = serializers.UUIDField()


class DriverVerifySerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=["verify", "reject"])


class LocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_meters = serializers.FloatField(required=False, allow_null=True)


class OnlineToggleSerializer(serializers.Serializer):
    is_online = serializers.BooleanField()


class PinCompleteSerializer(serializers.Serializer):
    pickup_code = serializers.CharField()


class DriverProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverProfile
        fields = [
            "id",
            "registration_id",
            "vehicle_type",
            "plate_number",
            "approved_corridor",
            "verification_status",
            "is_online",
            "created_at",
        ]
        read_only_fields = fields


class DriverLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverLocation
        fields = ["latitude", "longitude", "accuracy_meters", "recorded_at"]
        read_only_fields = ["recorded_at"]
