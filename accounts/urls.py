from django.urls import path

from drivers.views import DriverRegisterView, DriverVerifyView

from .views import LoginView, OTPRequestView, OTPVerifyView, SignupView

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("otp/request/", OTPRequestView.as_view(), name="otp-request"),
    path("otp/verify/", OTPVerifyView.as_view(), name="otp-verify"),
    path("login/", LoginView.as_view(), name="login"),
    path("driver/register/", DriverRegisterView.as_view(), name="driver-register"),
    path("driver/verify/", DriverVerifyView.as_view(), name="driver-verify"),
]
