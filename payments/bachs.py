"""Bachs checkout adapter.

Sandbox stub until the Bachs docs land (design spec §8b open detail): without
BACHS_API_URL configured, sessions are stubbed with a `sandbox-` reference and
a placeholder redirect URL. Payment is ONLY ever confirmed by the verified
webhook — never by the redirect — so the stub is safe for demo use. The demo or
simulator drives confirmation through the real webhook endpoint.
"""

import uuid

from django.conf import settings


def create_checkout_session(tip):
    """Return (reference, redirect_url) for a pending tip."""
    api_url = getattr(settings, "BACHS_API_URL", "") or ""
    if api_url:
        return _create_real_session(tip, api_url)
    reference = f"sandbox-{uuid.uuid4().hex[:12]}"
    return reference, f"https://sandbox.bachs.example/checkout/{reference}"


def _create_real_session(tip, api_url):
    """Real Bachs session creation. Shape TBD from Bachs docs — swap in here
    without touching callers."""
    import urllib.request
    import json

    payload = json.dumps(
        {
            "amount": str(tip.amount),
            "currency": tip.currency,
            "reference": f"omnipax-{tip.id}",
            "callback_url": getattr(settings, "BACHS_CALLBACK_URL", ""),
        }
    ).encode()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/checkout/sessions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.BACHS_SECRET_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        body = json.loads(res.read().decode())
    return body["reference"], body["redirect_url"]
