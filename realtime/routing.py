"""WebSocket URL patterns."""

from django.urls import path

from .consumers import DriverConsumer

websocket_urlpatterns = [
    path("ws/driver/", DriverConsumer.as_asgi()),
]
