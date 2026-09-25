"""Outbound realtime publishes. Enhancement-only: failures never break REST flows.

Groups: `junction_{id}` carries aggregate demand deltas (counts only, never
individual pins); `driver_{id}` carries targeted emergency-page alerts.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def junction_group(junction_id):
    return f"junction_{junction_id}"


def driver_group(driver_id):
    return f"driver_{driver_id}"


def _publish(group, event):
    try:
        async_to_sync(get_channel_layer().group_send)(group, event)
    except Exception:
        logger.warning("realtime publish to %s failed", group, exc_info=True)


def publish_demand(junction_id):
    """Aggregate demand delta for a junction group."""
    from rides.models import Pin

    count = Pin.objects.filter(
        junction_id=junction_id, status=Pin.Status.ACTIVE
    ).count()
    _publish(
        junction_group(junction_id),
        {
            "type": "demand.event",
            "junction_id": str(junction_id),
            "active_pins": count,
        },
    )


def publish_pin_event(junction_id, kind, pin_id):
    """Lifecycle notice (reserved/completed/cancelled/expired) for a junction."""
    _publish(
        junction_group(junction_id),
        {
            "type": "pin.event",
            "kind": kind,
            "pin_id": str(pin_id),
            "junction_id": str(junction_id),
        },
    )


def publish_page(driver_id, payload):
    """Targeted emergency-page alert to one driver's personal group."""
    _publish(driver_group(driver_id), {"type": "page.event", **payload})
