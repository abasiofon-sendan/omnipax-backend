from django.urls import path

from .views import BachsWebhookView

urlpatterns = [
    path("webhook/bachs/", BachsWebhookView.as_view(), name="bachs-webhook"),
]
