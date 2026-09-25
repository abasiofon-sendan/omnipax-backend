from django.urls import path

from payments.views import TipInitiateView

from .views import ActivePinView, PinCancelView, PinCreateView, PinStatusView

urlpatterns = [
    path("", PinCreateView.as_view(), name="pin-create"),
    path("active/", ActivePinView.as_view(), name="pin-active"),
    path("<uuid:pin_id>/cancel/", PinCancelView.as_view(), name="pin-cancel"),
    path("<uuid:pin_id>/status/", PinStatusView.as_view(), name="pin-status"),
    path("<uuid:pin_id>/tip/", TipInitiateView.as_view(), name="pin-tip"),
]
