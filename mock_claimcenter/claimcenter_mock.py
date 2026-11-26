"""STAND-IN for Guidewire ClaimCenter. NOT Guidewire software.

Mimics the documented Cloud API FNOL surface so the intake app can be demoed end to end without a licensed
ClaimCenter tenant:
  POST  /oauth2/token                                  (client_credentials, like Guidewire Hub)
  GET   /cc/rest/claim/v1/claims                       list claims
  POST  /cc/rest/claim/v1/claims                       create draft claim (policy must exist + be in force)
  GET   /cc/rest/claim/v1/claims/{id}
  PATCH /cc/rest/claim/v1/claims/{id}                  e.g. set reporter
  POST  /cc/rest/claim/v1/claims/{id}/contacts         create ClaimContact
  POST  /cc/rest/claim/v1/claims/{id}/submit           draft -> open; requires reporter
  GET   /cc/rest/common/v1/typelists/LossCause
Honors GW-DBTransaction-ID (duplicate => 400 AlreadyExecutedException). Data is in memory.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="ClaimCenter stand-in (mock, not Guidewire)")

CLIENT_ID = os.getenv("MOCK_CC_CLIENT_ID", "fnol-intake-demo")
CLIENT_SECRET = os.getenv("MOCK_CC_CLIENT_SECRET", "stand-in-secret")
POLICY_FILE = Path(os.getenv("POLICY_SEED_FILE", Path(__file__).resolve().parents[1] / "samples" / "policies.json"))
LOSS_CAUSES = [
    "vehcollision",
    "theftentire",
    "glassbreakage",
    "fire",
    "waterdamage",
    "hail",
    "burglary",
    "vandalism",
    "otherobjcoll",
    "other",
]

TOKENS: dict[str, float] = {}
CLAIMS: dict[str, dict[str, Any]] = {}
CONTACTS: dict[str, dict[str, Any]] = {}
TX_SEEN: set[str] = set()
POLICIES: dict[str, dict[str, Any]] = (
    {p["policy_number"]: p for p in json.loads(POLICY_FILE.read_text())} if POLICY_FILE.exists() else {}
)
SEQ = {"draft": 0, "open": 0, "id": 1000}


def err(status: int, user_message: str, error_code: str = "BadInputException") -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"status": status, "errorCode": error_code, "userMessage": user_message}
    )


def auth(authorization: str | None) -> None:
    tok = (authorization or "").removeprefix("Bearer ").strip()
    if not tok or TOKENS.get(tok, 0) < time.time():
        raise HTTPException(401, "Invalid or expired token")


def tx_guard(tx: str | None) -> JSONResponse | None:
    if tx:
        if tx in TX_SEEN:
            return err(400, f"The transaction with ID '{tx}' has already been executed", "AlreadyExecutedException")
        TX_SEEN.add(tx)
    return None


def envelope(c: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"attributes": c, "checksum": "0", "links": {"self": {"href": f"/claim/v1/claims/{c['id']}"}}}}


@app.post("/oauth2/token")
def token(
    grant_type: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...), scope: str = Form("")
) -> dict[str, Any]:
    if grant_type != "client_credentials" or client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
        raise HTTPException(401, "invalid_client")
    t = secrets.token_urlsafe(24)
    TOKENS[t] = time.time() + 3600
    return {"token_type": "Bearer", "expires_in": 3600, "access_token": t, "scope": scope}


@app.get("/cc/rest/claim/v1/claims")
def list_claims(authorization: str | None = Header(None), pageSize: int = 25) -> dict[str, Any]:  # noqa: N803
    auth(authorization)
    items = sorted(CLAIMS.values(), key=lambda c: c["id"], reverse=True)[:pageSize]
    return {"count": len(items), "data": [envelope(c)["data"] for c in items]}


@app.post("/cc/rest/claim/v1/claims")
def create_claim(
    body: dict = Body(...),
    authorization: str | None = Header(None),
    gw_tx: str | None = Header(None, alias="GW-DBTransaction-ID"),
):
    auth(authorization)
    if (dup := tx_guard(gw_tx)) is not None:
        return dup
    a = (body.get("data") or {}).get("attributes") or {}
    pn, ld = a.get("policyNumber"), a.get("lossDate")
    if not pn or not ld:
        return err(400, "policyNumber and lossDate are required")
    try:
        d = datetime.fromisoformat(ld.replace("Z", "+00:00")).date()
    except ValueError:
        return err(400, f"Invalid lossDate '{ld}'")
    pol = POLICIES.get(pn)
    if (
        not pol
        or pol["status"] != "inforce"
        or not (date.fromisoformat(pol["effective_date"]) <= d <= date.fromisoformat(pol["expiration_date"]))
    ):
        return err(400, f"No policy was found with policy number {pn} for loss date {ld}")
    cause = (a.get("lossCause") or {}).get("code")
    if cause and cause not in LOSS_CAUSES:
        return err(400, f"Unknown typecode '{cause}' for typelist LossCause")
    SEQ["draft"] += 1
    SEQ["id"] += 1
    cid = f"cc:{SEQ['id']}"
    c = {
        "id": cid,
        "claimNumber": f"999-99-{SEQ['draft']:06d}",
        "state": {"code": "draft", "name": "Draft"},
        "policyNumber": pn,
        "lossDate": ld,
        "lossCause": {"code": cause} if cause else None,
        "description": a.get("description"),
        "reporter": None,
        "contacts": [],
        "createdDate": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    CLAIMS[cid] = c
    return JSONResponse(status_code=201, content=envelope(c))


@app.get("/cc/rest/claim/v1/claims/{cid}")
def get_claim(cid: str, authorization: str | None = Header(None)):
    auth(authorization)
    if cid not in CLAIMS:
        return err(404, f"Claim {cid} not found", "NotFoundException")
    return envelope(CLAIMS[cid])


@app.post("/cc/rest/claim/v1/claims/{cid}/contacts")
def create_contact(
    cid: str,
    body: dict = Body(...),
    authorization: str | None = Header(None),
    gw_tx: str | None = Header(None, alias="GW-DBTransaction-ID"),
):
    auth(authorization)
    if (dup := tx_guard(gw_tx)) is not None:
        return dup
    if cid not in CLAIMS:
        return err(404, f"Claim {cid} not found", "NotFoundException")
    a = (body.get("data") or {}).get("attributes") or {}
    if a.get("contactSubtype") not in ("Person", "Company") or not a.get("lastName"):
        return err(400, "contactSubtype and lastName are required")
    SEQ["id"] += 1
    ct = {"id": f"cc:{SEQ['id']}", **a, "displayName": f"{a.get('firstName', '')} {a['lastName']}".strip()}
    CONTACTS[ct["id"]] = ct
    CLAIMS[cid]["contacts"].append(ct["id"])
    return JSONResponse(status_code=201, content={"data": {"attributes": ct}})


@app.patch("/cc/rest/claim/v1/claims/{cid}")
def patch_claim(
    cid: str,
    body: dict = Body(...),
    authorization: str | None = Header(None),
    gw_tx: str | None = Header(None, alias="GW-DBTransaction-ID"),
):
    auth(authorization)
    if (dup := tx_guard(gw_tx)) is not None:
        return dup
    if cid not in CLAIMS:
        return err(404, f"Claim {cid} not found", "NotFoundException")
    a = (body.get("data") or {}).get("attributes") or {}
    if "reporter" in a:
        rid = (a["reporter"] or {}).get("id")
        if rid not in CONTACTS:
            return err(400, f"Contact {rid} not found on claim")
        CLAIMS[cid]["reporter"] = {"id": rid, "displayName": CONTACTS[rid]["displayName"]}
    for k in ("description",):
        if k in a:
            CLAIMS[cid][k] = a[k]
    return envelope(CLAIMS[cid])


@app.post("/cc/rest/claim/v1/claims/{cid}/submit")
def submit(
    cid: str, authorization: str | None = Header(None), gw_tx: str | None = Header(None, alias="GW-DBTransaction-ID")
):
    auth(authorization)
    if (dup := tx_guard(gw_tx)) is not None:
        return dup
    c = CLAIMS.get(cid)
    if not c:
        return err(404, f"Claim {cid} not found", "NotFoundException")
    if c["state"]["code"] != "draft":
        return err(400, f"Claim {c['claimNumber']} is not a draft")
    if not c.get("reporter"):
        return err(
            400,
            f"Could not submit draft claim {c['claimNumber']}: CLV04000 - reporter is required",
            "ValidationException",
        )
    SEQ["open"] += 1
    c["claimNumber"] = f"000-00-{SEQ['open']:06d}"
    c["state"] = {"code": "open", "name": "Open"}
    return envelope(c)


@app.get("/cc/rest/common/v1/typelists/LossCause")
def typelist(authorization: str | None = Header(None)) -> dict[str, Any]:
    auth(authorization)
    return {"data": {"attributes": {"name": "LossCause", "typeKeys": [{"code": c, "name": c} for c in LOSS_CAUSES]}}}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "claimcenter-stand-in"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    rows = "".join(
        f"<tr><td>{c['claimNumber']}</td><td>{c['state']['name']}</td><td>{c['policyNumber']}</td>"
        f"<td>{c['lossDate'][:10]}</td><td>{(c.get('lossCause') or {}).get('code', '')}</td>"
        f"<td>{(c.get('reporter') or {}).get('displayName', '')}</td></tr>"
        for c in sorted(CLAIMS.values(), key=lambda c: c["id"], reverse=True)
    )
    return (
        "<html><head><title>ClaimCenter stand-in</title><style>body{font-family:system-ui;margin:40px}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px 10px}"
        ".b{background:#fff3cd;padding:10px;border:1px solid #e0c36a;margin-bottom:16px}</style></head><body>"
        "<div class=b><b>STAND-IN, not Guidewire ClaimCenter.</b> A local mock that follows the published "
        "Cloud API FNOL request/response shapes for demos and tests.</div>"
        f"<h2>Claims received ({len(CLAIMS)})</h2><table><tr><th>Claim #</th><th>State</th><th>Policy</th>"
        f"<th>Loss date</th><th>Loss cause</th><th>Reporter</th></tr>{rows}</table></body></html>"
    )
