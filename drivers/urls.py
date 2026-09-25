from django.urls import path

from .views import (
    DriverPinsView,
    LocationHeartbeatView,
    OnlineToggleView,
    PinAcceptView,
    PinCompleteView,
    PinDeclineView,
    ZonesView,
)

urlpatterns = [
    path("location/", LocationHeartbeatView.as_view(), name="driver-location"),
    path("online/", OnlineToggleView.as_view(), name="driver-online"),
    path("zones/", ZonesView.as_view(), name="driver-zones"),
    path("pins/", DriverPinsView.as_view(), name="driver-pins"),
    path("pins/<uuid:pin_id>/accept/", PinAcceptView.as_view(), name="pin-accept"),
    path("pins/<uuid:pin_id>/decline/", PinDeclineView.as_view(), name="pin-decline"),
    path("pins/<uuid:pin_id>/complete/", PinCompleteView.as_view(), name="pin-complete"),
]
