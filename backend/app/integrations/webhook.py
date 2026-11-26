"""Generic webhook + generic REST adapters (Duck Creek, Majesco).

Duck Creek Claims and Majesco Claims expose REST APIs whose resource shapes are tenant-configured, so these
adapters send a documented, flat FNOL JSON to a configurable endpoint path with OAuth2. The field mapping
must be confirmed against the carrier's API spec before go-live (shown as a notice in the UI)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import Integration
from .base import Checkpoint, ClaimsAdapter, PushError, PushResult, val


def flat_payload(fields: dict[str, Any], reference: str) -> dict[str, Any]:
    keys = [
        "policy_number",
        "line_of_business",
        "loss_date",
        "loss_time",
        "loss_cause",
        "loss_location",
        "description",
        "insured_name",
        "insured_phone",
        "insured_email",
        "reporter_name",
        "reporter_relationship",
        "other_parties",
        "vehicle_or_property",
        "police_report_number",
        "injuries",
        "estimated_amount",
        "currency",
        "line_items",
    ]
    return {
        "type": "fnol.claim",
        "reference": reference,
        "submitted_at": datetime.now(UTC).isoformat(),
        "claim": {k: val(fields, k) for k in keys},
    }


class WebhookAdapter(ClaimsAdapter):
    kind = "webhook"
    label = "Generic webhook (signed JSON)"

    def _sign(self, body: bytes) -> dict[str, str]:
        if not self.secret:
            return {}
        sig = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        return {"X-FNOL-Signature": f"sha256={sig}"}

    def test_connection(self) -> tuple[bool, str]:
        body = json.dumps({"type": "fnol.ping"}).encode()
        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(
                    self.integ.base_url, content=body, headers={"Content-Type": "application/json", **self._sign(body)}
                )
        except httpx.HTTPError as e:
            return False, f"Cannot reach webhook: {type(e).__name__}"
        return (r.status_code < 300, f"Webhook answered {r.status_code}")

    def build_payload(self, fields: dict[str, Any]) -> dict[str, Any]:
        return flat_payload(fields, "preview")

    def push(
        self, fields: dict[str, Any], push_key: str, state: dict[str, Any], checkpoint: Checkpoint, reference: str
    ) -> PushResult:
        body = json.dumps(flat_payload(fields, reference)).encode()
        with httpx.Client(timeout=30) as c:
            try:
                r = c.post(
                    self.integ.base_url,
                    content=body,
                    headers={"Content-Type": "application/json", "Idempotency-Key": push_key, **self._sign(body)},
                )
            except httpx.HTTPError as e:
                raise PushError(f"Webhook unreachable: {type(e).__name__}") from e
        self._log("POST", self.integ.base_url, r.status_code, json.loads(body), r.text[:300])
        if r.status_code >= 300:
            raise PushError(f"Webhook returned {r.status_code}", retryable=r.status_code >= 500, calls=self.calls)
        try:
            ext = r.json().get("claimNumber") or r.json().get("id")
        except ValueError:
            ext = None
        return PushResult(external_id=ext, claim_number=ext or reference, state="accepted", calls=self.calls)


class GenericRestAdapter(WebhookAdapter):
    """Duck Creek / Majesco: OAuth2 + POST to options['claims_path'] (default /claims)."""

    def __init__(self, integ: Integration, secret: str, kind: str, label: str) -> None:
        super().__init__(integ, secret)
        self.kind = kind
        self.label = label

    @property
    def url(self) -> str:
        return self.integ.base_url.rstrip("/") + (self.integ.options or {}).get("claims_path", "/claims")

    def test_connection(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=15) as c:
                h = self.auth_headers(c)
                r = c.get(self.url, headers=h)
        except PushError as e:
            return False, str(e)
        except httpx.HTTPError as e:
            return False, f"Cannot reach {self.url}: {type(e).__name__}"
        if r.status_code in (401, 403):
            return False, f"Credentials rejected ({r.status_code})"
        return (r.status_code < 400, f"{self.label} answered {r.status_code}")

    def push(
        self, fields: dict[str, Any], push_key: str, state: dict[str, Any], checkpoint: Checkpoint, reference: str
    ) -> PushResult:
        body = flat_payload(fields, reference)
        with httpx.Client(timeout=30) as c:
            h = {"Content-Type": "application/json", "Idempotency-Key": push_key, **self.auth_headers(c)}
            try:
                r = c.post(self.url, json=body, headers=h)
            except httpx.HTTPError as e:
                raise PushError(f"{self.label} unreachable: {type(e).__name__}") from e
        self._log("POST", self.url, r.status_code, body, r.text[:300])
        if r.status_code >= 300:
            raise PushError(f"{self.label} returned {r.status_code}", retryable=r.status_code >= 500, calls=self.calls)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        num = data.get("claimNumber") or data.get("claim_number") or data.get("id")
        return PushResult(external_id=data.get("id"), claim_number=num, state="accepted", calls=self.calls)
