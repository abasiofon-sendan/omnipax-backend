from celery import shared_task
from django.utils import timezone

from .models import EmergencyPage, Pin
from .services import release_reservation


@shared_task
def expire_pins():
    """Beat job (every PIN_EXPIRY_SWEEP_SECONDS): expire overdue pins and
    release overdue reservations. No refund logic — tips stay `paid`."""
    from realtime.broadcast import publish_demand

    now = timezone.now()
    touched_junctions = set()

    stale_ids = list(
        Pin.objects.filter(status=Pin.Status.ACTIVE, expires_at__lt=now).values_list(
            "id", "junction_id"
        )
    )
    expired = (
        Pin.objects.filter(status=Pin.Status.ACTIVE, expires_at__lt=now).update(
            status=Pin.Status.EXPIRED
        )
    )
    touched_junctions.update(junction_id for _, junction_id in stale_ids)

    released = 0
    overdue = Pin.objects.filter(
        status=Pin.Status.RESERVED, reservation_expires_at__lt=now
    ).select_related("reserved_by")
    for pin in overdue:
        if pin.expires_at < now:
            pin.status = Pin.Status.EXPIRED
            pin.reserved_by = None
            pin.save(update_fields=["status", "reserved_by"])
        else:
            release_reservation(pin, EmergencyPage.Outcome.EXPIRED)
        touched_junctions.add(pin.junction_id)
        released += 1

    # Paged pages whose accept deadline passed while the pin stayed active
    # (no accept/decline arrived): mark expired so re-paging can move on.
    stale = EmergencyPage.objects.filter(
        outcome=EmergencyPage.Outcome.PAGED,
        pin__status=Pin.Status.ACTIVE,
        pin__reservation_expires_at__lt=now,
    ).select_related("pin")
    for page in stale:
        page.outcome = EmergencyPage.Outcome.EXPIRED
        page.resolved_at = now
        page.save(update_fields=["outcome", "resolved_at"])
        pin = page.pin
        pin.reservation_expires_at = None
        pin.save(update_fields=["reservation_expires_at"])
        released += 1

    for junction_id in touched_junctions:
        publish_demand(junction_id)

    return {"expired": expired, "released": released}
