"""Driver WebSocket consumer.

Connect: ws/driver/?token=<JWT access token>. The driver joins every active
junction group in their approved corridor (heat) plus their personal group
(emergency-page alerts). Polling endpoints remain the fallback — this socket
is enhancement-only.
"""

from urllib.parse import parse_qsl

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.models import User


@database_sync_to_async
def _authenticate(token):
    try:
        validated = JWTAuthentication().get_validated_token(token or "")
        return JWTAuthentication().get_user(validated)
    except Exception:
        return None


@database_sync_to_async
def _driver_setup(user):
    try:
        profile = user.driver_profile
    except Exception:
        return None, []
    junction_ids = list(
        profile.approved_corridor.junctions.filter(is_active=True).values_list(
            "id", flat=True
        )
    )
    return profile, junction_ids


class DriverConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        params = dict(parse_qsl(self.scope.get("query_string", b"").decode()))
        user = await _authenticate(params.get("token"))
        if user is None or user.role != User.Role.DRIVER:
            await self.close()
            return
        profile, junction_ids = await _driver_setup(user)
        if profile is None:
            await self.close()
            return
        self.groups = [f"junction_{jid}" for jid in junction_ids] + [
            f"driver_{profile.id}"
        ]
        for group in self.groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        for group in getattr(self, "groups", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def demand_event(self, event):
        await self.send_json(
            {
                "kind": "demand",
                "junction_id": event["junction_id"],
                "active_pins": event["active_pins"],
            }
        )

    async def page_event(self, event):
        payload = {k: v for k, v in event.items() if k != "type"}
        await self.send_json({"kind": "emergency_page", **payload})

    async def pin_event(self, event):
        await self.send_json(
            {
                "kind": "pin",
                "event": event["kind"],
                "pin_id": event["pin_id"],
                "junction_id": event["junction_id"],
            }
        )
