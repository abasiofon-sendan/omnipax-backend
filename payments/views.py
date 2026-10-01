import hashlib
import hmac
import json

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from rides.models import Pin

from .models import Tip
from .services import confirm_payment_by_reference, initiate_tip


class TipInitiateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class TipInitiateView(APIView):
    """POST /api/pins/{id}/tip/. Passenger-only (own pin)."""

    serializer_class = TipInitiateSerializer

    @extend_schema(
        request=TipInitiateSerializer, responses=OpenApiTypes.OBJECT, tags=["payments"]
    )
    def post(self, request, pin_id):
        pin = get_object_or_404(Pin, id=pin_id, passenger=request.user)
        if pin.status == Pin.Status.RESERVED:
            return Response(
                {"detail": "Pin is already reserved by a driver."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if pin.status != Pin.Status.ACTIVE:
            return Response(
                {"detail": f"Pin is {pin.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        amount = request.data.get("amount")
        tip, redirect_url, repaged = initiate_tip(pin, amount=amount)
        body = {"tip_id": str(tip.id), "status": tip.status}
        if redirect_url:
            body["redirect_url"] = redirect_url
        if repaged:
            body["repaged"] = True
        return Response(body, status=status.HTTP_201_CREATED)


class BachsWebhookView(APIView):
    """POST /api/payments/webhook/bachs/. AllowAny + mandatory HMAC check.

    Assumed contract (correct against Bachs docs when they land): JSON body
    {"reference": ..., "status": "paid"|"failed"}, signature =
    hex(HMAC-SHA256(raw_body, BACHS_WEBHOOK_SECRET)) in X-Bachs-Signature.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TipInitiateSerializer

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["payments"]
    )
    def post(self, request):
        secret = getattr(settings, "BACHS_WEBHOOK_SECRET", "") or ""
        if not secret:
            return Response(
                {"detail": "Webhook not configured."},
                status=status.HTTP_403_FORBIDDEN,
            )
        signature = request.headers.get("X-Bachs-Signature", "")
        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return Response(
                {"detail": "Invalid signature."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            payload = json.loads(request.body.decode())
        except (ValueError, UnicodeDecodeError):
            return Response(
                {"detail": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST
            )
        reference = payload.get("reference")
        if not reference:
            return Response(
                {"detail": "Missing reference."}, status=status.HTTP_400_BAD_REQUEST
            )
        tip, newly_paid, page = confirm_payment_by_reference(reference)
        if tip is None:
            return Response(
                {"detail": "Unknown reference."}, status=status.HTTP_404_NOT_FOUND
            )
        if payload.get("status") == "failed" and tip.status == Tip.Status.PENDING:
            tip.status = Tip.Status.FAILED
            tip.save(update_fields=["status"])
        return Response(
            {
                "tip_id": str(tip.id),
                "status": tip.status,
                "processed": newly_paid,
                "paged_driver": str(page.driver_id) if page else None,
            }
        )
