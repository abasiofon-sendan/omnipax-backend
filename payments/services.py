"""Tip lifecycle + emergency paging (design spec §7 rules 6)."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from drivers.visibility import _ranked_candidates
from rides.models import EmergencyPage, Pin

from .bachs import create_checkout_session
from .models import Tip


def page_nearest_driver(pin, exclude_driver_ids=()):
    """Page the nearest eligible driver: verified, online, fresh location,
    same corridor, matching vehicle type, not previously paged.

    Sets the accept deadline on the pin (status stays `active` until accept).
    Returns the EmergencyPage, or None when nobody qualifies.
    """
    exclude = set(exclude_driver_ids)
    already_paged = set(
        EmergencyPage.objects.filter(pin=pin).values_list("driver_id", flat=True)
    )
    for profile, dist in _ranked_candidates(pin.junction, pin.corridor_id):
        if profile.id in exclude or profile.id in already_paged:
            continue
        if profile.vehicle_type != pin.vehicle_type:
            continue
        now = timezone.now()
        with transaction.atomic():
            page = EmergencyPage.objects.create(
                pin=pin, driver=profile, outcome=EmergencyPage.Outcome.PAGED
            )
            pin.reservation_expires_at = now + timedelta(
                seconds=settings.EMERGENCY_ACCEPT_SECONDS
            )
            pin.save(update_fields=["reservation_expires_at"])
        from realtime.broadcast import publish_page

        publish_page(
            profile.id,
            {
                "pin_id": str(pin.id),
                "junction_id": str(pin.junction_id),
                "junction": pin.junction.name,
                "direction": pin.direction,
                "vehicle_type": pin.vehicle_type,
                "priority": pin.priority,
            },
        )
        return page
    return None


def initiate_tip(pin, amount=None):
    """Create (or reuse) the pin's tip and return (tip, redirect_url, repaged).

    Already-paid tip on a live, unreserved pin = re-page request: page the
    next-nearest un-paged driver without charging again.
    """
    tip, created = Tip.objects.get_or_create(pin=pin)
    if amount is not None and created:
        tip.amount = amount
        tip.save(update_fields=["amount"])

    if tip.status == Tip.Status.PAID:
        if pin.status != Pin.Status.ACTIVE:
            return tip, None, False
        page = page_nearest_driver(pin)
        return tip, None, page is not None

    if not tip.bachs_reference:
        reference, redirect_url = create_checkout_session(tip)
        tip.bachs_reference = reference
        tip.save(update_fields=["bachs_reference"])
    else:
        _, redirect_url = create_checkout_session(tip)
        redirect_url = redirect_url  # stub regenerates a URL; reference is stable
    return tip, redirect_url, False


def confirm_payment_by_reference(reference):
    """Idempotent webhook confirmation. Returns (tip, newly_paid, page)."""
    try:
        tip = Tip.objects.select_related("pin").get(bachs_reference=reference)
    except Tip.DoesNotExist:
        return None, False, None
    if tip.status == Tip.Status.PAID:
        return tip, False, None
    with transaction.atomic():
        tip.status = Tip.Status.PAID
        tip.paid_at = timezone.now()
        tip.save(update_fields=["status", "paid_at"])
        pin = tip.pin
        if pin.status == Pin.Status.ACTIVE:
            pin.priority = Pin.Priority.PRIORITY
            pin.save(update_fields=["priority"])
            page = page_nearest_driver(pin)
        else:
            page = None
    return tip, True, page
