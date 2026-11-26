"""Guidewire ClaimCenter Cloud API adapter.

Follows the documented FNOL flow (docs.guidewire.com > Cloud API > ClaimCenter > Executing FNOL):
  1. POST   /claim/v1/claims                      create a draft claim (policyNumber + lossDate minimum)
  2. POST   /claim/v1/claims/{claimId}/contacts   create ClaimContacts (reporter, other parties)
  3. PATCH  /claim/v1/claims/{claimId}            set reporter (base config needs one to submit)
  4. POST   /claim/v1/claims/{claimId}/submit     draft -> open claim, assigns the open claim number
Payloads use the Cloud API envelope {"data": {"attributes": {...}}}; typecodes are {"code": ...}.
Auth: OAuth2 client credentials from Guidewire Hub (Bearer token) or Basic auth for self-managed/dev.
Idempotency: every committing call carries GW-DBTransaction-ID (Cloud API duplicate-transaction guard) and
each step is checkpointed, so a retry resumes instead of creating a second claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .base import Checkpoint, ClaimsAdapter, PushError, PushResult, split_name, val

# Our loss causes -> ClaimCenter LossCause typecodes. "vehcollision" is from Guidewire's own FNOL sample; the rest
# are common base-config codes. "Test connection" fetches GET /common/v1/typelists/LossCause from the tenant and
# reports any mapped code that does not exist there. Override per tenant in options["loss_cause_map"].
DEFAULT_LOSS_CAUSE_MAP = {
    "auto_collision": "vehcollision",
    "auto_theft": "theftentire",
    "glass_damage": "glassbreakage",
    "fire": "fire",
    "water_damage": "waterdamage",
    "wind_hail": "hail",
    "theft_burglary": "burglary",
    "vandalism": "vandalism",
    "liability_injury": "otherobjcoll",
    "other": "other",
}


def _collect_codes(obj: Any) -> set[str]:
    """Collect every "code" value in a typelist response (tolerant of envelope differences across releases)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        if isinstance(obj.get("code"), str):
            out.add(obj["code"])
        for v in obj.values():
            out |= _collect_codes(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _collect_codes(v)
    return out


class GuidewireAdapter(ClaimsAdapter):
    kind = "guidewire"
    label = "Guidewire ClaimCenter (Cloud API)"

    @property
    def base(self) -> str:
        return self.integ.base_url.rstrip("/")

    def _headers(self, client: httpx.Client, tx: str | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json", **self.auth_headers(client)}
        if tx:
            h["GW-DBTransaction-ID"] = tx
        return h

    def test_connection(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=20) as c:
                r = c.get(f"{self.base}/claim/v1/claims", params={"pageSize": 1}, headers=self._headers(c))
        except PushError as e:
            return False, str(e)
        except httpx.HTTPError as e:
            return False, f"Cannot reach {self.base}: {type(e).__name__}"
        if r.status_code == 200:
            return True, "Authenticated and reached GET /claim/v1/claims. " + self._check_loss_causes()
        if r.status_code in (401, 403):
            return False, f"Reached ClaimCenter but credentials were rejected ({r.status_code})"
        return False, f"Unexpected response {r.status_code} from GET /claim/v1/claims"

    def _check_loss_causes(self) -> str:
        cmap = {**DEFAULT_LOSS_CAUSE_MAP, **(self.integ.options or {}).get("loss_cause_map", {})}
        try:
            with httpx.Client(timeout=20) as c:
                r = c.get(f"{self.base}/common/v1/typelists/LossCause", headers=self._headers(c))
            if r.status_code != 200:
                return f"LossCause typelist not readable ({r.status_code}); mapping unchecked."
            codes = _collect_codes(r.json())
        except (httpx.HTTPError, ValueError, PushError):
            return "LossCause typelist not readable; mapping unchecked."
        missing = sorted({v for v in cmap.values() if v not in codes})
        if missing:
            return f"Loss-cause codes missing in this tenant: {', '.join(missing)} (edit the mapping)."
        return f"All {len(set(cmap.values()))} mapped loss-cause codes exist in the tenant's LossCause typelist."

    def build_payload(self, fields: dict[str, Any]) -> dict[str, Any]:
        cmap = {**DEFAULT_LOSS_CAUSE_MAP, **(self.integ.options or {}).get("loss_cause_map", {})}
        loss_date = val(fields, "loss_date")
        loss_time = val(fields, "loss_time") or "12:00"
        try:
            iso = datetime.fromisoformat(f"{loss_date}T{loss_time}").strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except (TypeError, ValueError):
            iso = f"{loss_date}T12:00:00.000Z"
        desc_parts = [val(fields, "description") or ""]
        if val(fields, "loss_location"):
            desc_parts.append(f"Location: {val(fields, 'loss_location')}")
        if val(fields, "vehicle_or_property"):
            desc_parts.append(f"Vehicle/property: {val(fields, 'vehicle_or_property')}")
        if val(fields, "police_report_number"):
            desc_parts.append(f"Police report: {val(fields, 'police_report_number')}")
        if val(fields, "estimated_amount") is not None:
            desc_parts.append(f"Estimated amount: {val(fields, 'estimated_amount')} {val(fields, 'currency') or ''}")
        attrs: dict[str, Any] = {
            "policyNumber": val(fields, "policy_number"),
            "lossDate": iso,
            "lossCause": {"code": cmap.get(val(fields, "loss_cause") or "other", "other")},
            "description": " | ".join(p for p in desc_parts if p).strip()[:1999],
        }
        return {"data": {"attributes": attrs}}

    def _contact_payload(self, name: str | None, phone: str | None = None) -> dict[str, Any]:
        first, last = split_name(name)
        attrs: dict[str, Any] = {"contactSubtype": "Person", "firstName": first, "lastName": last}
        if phone:
            attrs["cellPhone"] = {"phoneNumber": phone}
        return {"data": {"attributes": attrs}}

    def _call(self, c: httpx.Client, method: str, path: str, body: dict | None, tx: str | None) -> dict[str, Any]:
        url = f"{self.base}{path}"
        try:
            r = c.request(method, url, json=body, headers=self._headers(c, tx))
        except httpx.HTTPError as e:
            raise PushError(f"{method} {path} failed: {type(e).__name__}", retryable=True, calls=self.calls) from e
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:500]}
        self._log(method, url, r.status_code, body, data)
        if r.status_code >= 400:
            msg = data.get("userMessage") or data.get("message") or str(data)[:300]
            raise PushError(
                f"{method} {path} -> {r.status_code}: {msg}",
                retryable=r.status_code >= 500 or r.status_code == 429,
                calls=self.calls,
            )
        return data

    def push(
        self, fields: dict[str, Any], push_key: str, state: dict[str, Any], checkpoint: Checkpoint, reference: str
    ) -> PushResult:
        with httpx.Client(timeout=30) as c:
            claim_id = state.get("claim_id")
            if not claim_id:
                d = self._call(c, "POST", "/claim/v1/claims", self.build_payload(fields), f"{push_key}-create")
                claim_id = d["data"]["attributes"]["id"]
                state.update(claim_id=claim_id, draft_number=d["data"]["attributes"].get("claimNumber"))
                checkpoint(state)
            if not state.get("reporter_id"):
                d = self._call(
                    c,
                    "POST",
                    f"/claim/v1/claims/{claim_id}/contacts",
                    self._contact_payload(val(fields, "reporter_name")),
                    f"{push_key}-reporter",
                )
                state["reporter_id"] = d["data"]["attributes"]["id"]
                checkpoint(state)
            for i, p in enumerate(val(fields, "other_parties") or []):
                key = f"party_{i}"
                if state.get(key) or not isinstance(p, dict) or not p.get("name"):
                    continue
                d = self._call(
                    c,
                    "POST",
                    f"/claim/v1/claims/{claim_id}/contacts",
                    self._contact_payload(p.get("name"), p.get("phone")),
                    f"{push_key}-{key}",
                )
                state[key] = d["data"]["attributes"]["id"]
                checkpoint(state)
            if not state.get("reporter_set"):
                self._call(
                    c,
                    "PATCH",
                    f"/claim/v1/claims/{claim_id}",
                    {"data": {"attributes": {"reporter": {"id": state["reporter_id"]}}}},
                    f"{push_key}-patch-reporter",
                )
                state["reporter_set"] = True
                checkpoint(state)
            if not state.get("submitted"):
                d = self._call(c, "POST", f"/claim/v1/claims/{claim_id}/submit", None, f"{push_key}-submit")
                state.update(submitted=True, claim_number=d["data"]["attributes"].get("claimNumber"))
                checkpoint(state)
        return PushResult(
            external_id=claim_id, claim_number=state.get("claim_number"), state="submitted", calls=self.calls
        )
