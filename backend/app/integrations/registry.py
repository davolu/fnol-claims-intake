from __future__ import annotations

from ..models import Integration
from ..security import decrypt_secret
from .base import ClaimsAdapter
from .guidewire import GuidewireAdapter
from .webhook import GenericRestAdapter, WebhookAdapter

CATALOG = [
    {
        "kind": "guidewire",
        "label": "Guidewire ClaimCenter",
        "auth_modes": ["oauth2", "basic"],
        "notes": "Cloud API FNOL flow: draft claim -> contacts -> reporter -> submit. Token URL is your "
        "Guidewire Hub OAuth endpoint; scopes must include tenant.<tenantId>.",
        "verified_against": "docs.guidewire.com Cloud API Consumer Guide (Executing ClaimCenter FNOL)",
    },
    {
        "kind": "duckcreek",
        "label": "Duck Creek Claims",
        "auth_modes": ["oauth2"],
        "notes": "Sends flat FNOL JSON to your claims endpoint. Confirm field mapping with your Duck Creek API spec.",
    },
    {
        "kind": "majesco",
        "label": "Majesco Claims",
        "auth_modes": ["oauth2"],
        "notes": "Sends flat FNOL JSON to your claims endpoint. Confirm field mapping with your Majesco API spec.",
    },
    {
        "kind": "webhook",
        "label": "Generic webhook",
        "auth_modes": ["hmac", "none"],
        "notes": "POSTs signed JSON (X-FNOL-Signature: sha256 HMAC) with an Idempotency-Key header.",
    },
]


def get_adapter(integ: Integration) -> ClaimsAdapter:
    secret = decrypt_secret(integ.secret_encrypted)
    if integ.kind == "guidewire":
        return GuidewireAdapter(integ, secret)
    if integ.kind == "webhook":
        return WebhookAdapter(integ, secret)
    if integ.kind == "duckcreek":
        return GenericRestAdapter(integ, secret, "duckcreek", "Duck Creek Claims")
    if integ.kind == "majesco":
        return GenericRestAdapter(integ, secret, "majesco", "Majesco Claims")
    raise ValueError(f"Unknown integration kind {integ.kind}")
