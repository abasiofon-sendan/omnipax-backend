from rest_framework import serializers

from .models import Corridor, Junction, RestrictedZone


class CorridorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Corridor
        fields = ["id", "name", "description", "is_active"]
        read_only_fields = ["id"]


class JunctionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Junction
        fields = [
            "id",
            "name",
            "corridor",
            "latitude",
            "longitude",
            "is_active",
        ]
        read_only_fields = ["id"]


class RestrictedZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestrictedZone
        fields = [
            "id",
            "name",
            "junction",
            "coordinates",
            "restriction_type",
            "start_time",
            "end_time",
            "effective_date",
            "reason",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if (
            attrs.get("restriction_type") == RestrictedZone.RestrictionType.TIME_WINDOW
            and (not attrs.get("start_time") or not attrs.get("end_time"))
        ):
            raise serializers.ValidationError(
                "start_time and end_time are required for time_window zones."
            )
        return attrs
