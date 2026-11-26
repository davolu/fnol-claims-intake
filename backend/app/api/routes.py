from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import audit
from ..db import get_db
from ..email_connectors.connectors import CATALOG as EMAIL_CATALOG
from ..email_connectors.connectors import get_source
from ..ingest import ingest_bytes
from ..integrations.registry import CATALOG as CLAIMS_CATALOG
from ..integrations.registry import get_adapter
from ..models import AuditEvent, Claim, Document, EmailConnector, EvalRun, Integration, Job, Policy, utcnow
from ..pipeline import ocr
from ..pipeline.orchestrator import decide
from ..pipeline.validate import validate
from ..queue import enqueue
from ..schemas import FIELD_SPECS
from ..security import SecretsKeyMissing, encrypt_secret
from ..settings_store import get_runtime, update_runtime
from .deps import User, current_user, require_admin, require_edit
from .serialize import claim_detail, claim_summary, event_out, integration_out

router = APIRouter(prefix="/api")


# ---------------- intake ----------------
@router.post("/documents")
async def upload_documents(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    require_edit(user)
    results = []
    for f in files:
        data = await f.read()
        try:
            kind = ocr.sniff_kind(data, f.filename or "")
            if kind == "unknown":
                raise ValueError("Unsupported file type. Upload PDF, TIFF, PNG, JPEG, EML or TXT.")
            doc, claim, created = ingest_bytes(
                db, data, f.filename or "upload", f.content_type or "", source="upload", actor=user.actor
            )
            results.append(
                {
                    "filename": f.filename,
                    "claim_id": claim.id,
                    "reference": claim.reference,
                    "duplicate": not created,
                    "status": claim.status,
                }
            )
        except ValueError as e:
            results.append({"filename": f.filename, "error": str(e)})
    db.commit()
    return {"results": results}


# ---------------- claims ----------------
@router.get("/claims")
def list_claims(
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(Claim).order_by(Claim.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Claim.status.in_(status.split(",")))
    if q:
        stmt = stmt.where(Claim.reference.ilike(f"%{q}%"))
    return {"claims": [claim_summary(c, user) for c in db.scalars(stmt).all()]}


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    out = claim_detail(c, user)
    out["events"] = [event_out(e) for e in c.events]
    out["field_specs"] = FIELD_SPECS
    integ = db.query(Integration).filter(Integration.is_active.is_(True)).first()
    if integ is not None and user.can_see_pii:
        try:
            out["payload_preview"] = {
                "system": integ.kind,
                "stand_in": integ.is_stand_in,
                "body": get_adapter(integ).build_payload(
                    {k: v for k, v in (c.fields or {}).items() if not k.startswith("_")}
                ),
            }
        except Exception as e:  # noqa: BLE001
            out["payload_preview"] = {"error": str(e)}
    return out


class FieldEdit(BaseModel):
    fields: dict[str, Any]  # name -> new value


@router.patch("/claims/{claim_id}/fields")
def edit_fields(
    claim_id: str, body: FieldEdit, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    require_edit(user)
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    if c.status in ("pushed", "pushing"):
        raise HTTPException(409, "Claim already sent to the claims system")
    fields = dict(c.fields or {})
    diffs = []
    for k, v in body.fields.items():
        if k not in FIELD_SPECS:
            raise HTTPException(400, f"Unknown field {k}")
        old = (fields.get(k) or {}).get("value")
        if old == v:
            continue
        fields[k] = {
            **(fields.get(k) or {}),
            "value": v,
            "confidence": 1.0,
            "method": "human",
            "notes": [*((fields.get(k) or {}).get("notes") or []), f"edited by {user.name}"],
        }
        diffs.append({"field": k, "before": old, "after": v})
    c.fields = fields
    flag_modified(c, "fields")
    c.validation = validate(db, {k: v for k, v in fields.items() if not k.startswith("_")}, get_runtime(db))
    audit.record(db, "fields_edited", claim_id=c.id, actor=user.actor, details={"changes": diffs})
    db.commit()
    return claim_detail(c, user)


class ReviewAction(BaseModel):
    reason: str | None = None


@router.post("/claims/{claim_id}/approve")
def approve(
    claim_id: str, body: ReviewAction | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    require_edit(user)
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    if c.status not in ("needs_review", "push_failed", "failed"):
        raise HTTPException(409, f"Claim is {c.status}")
    fields = {k: v for k, v in (c.fields or {}).items() if not k.startswith("_")}
    issues = validate(db, fields, get_runtime(db))
    hard = [
        i
        for i in issues
        if i["severity"] == "error"
        and i["rule"]
        in (
            "required",
            "schema",
            "loss_date_not_future",
            "loss_date_format",
            "amounts_consistent",
            "policy_exists",
            "policy_in_force",
        )
    ]
    if hard:
        raise HTTPException(422, {"message": "Fix these before approving", "issues": hard})
    if not db.query(Integration).filter(Integration.is_active.is_(True)).first():
        raise HTTPException(409, "Activate a claims-system integration in Settings first")
    c.validation = issues
    c.status = "approved"
    c.reviewed_by = user.name
    c.reviewed_at = utcnow()
    audit.record(
        db,
        "approved",
        claim_id=c.id,
        actor=user.actor,
        details={"note": body.reason if body else None, "overridden": [i["rule"] for i in issues]},
    )
    enqueue(
        db,
        "push_claim",
        {"claim_id": c.id, "actor": user.actor},
        dedupe_key=f"push:{c.id}:{c.push_attempts}:{int(utcnow().timestamp())}",
    )
    db.commit()
    return claim_detail(c, user)


@router.post("/claims/{claim_id}/reject")
def reject(
    claim_id: str, body: ReviewAction, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    require_edit(user)
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    if c.status in ("pushed", "pushing"):
        raise HTTPException(409, "Claim already sent")
    if not (body.reason or "").strip():
        raise HTTPException(400, "A reason is required to reject")
    c.status = "rejected"
    c.reject_reason = body.reason
    c.reviewed_by = user.name
    c.reviewed_at = utcnow()
    audit.record(db, "rejected", claim_id=c.id, actor=user.actor, details={"reason": body.reason})
    db.commit()
    return claim_detail(c, user)


@router.post("/claims/{claim_id}/reprocess")
def reprocess(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    require_edit(user)
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    if c.status in ("pushed", "pushing", "processing"):
        raise HTTPException(409, f"Claim is {c.status}")
    c.status = "queued"
    # Cancel any retry of an earlier run still waiting in the queue, so one claim is never processed twice.
    for old in db.scalars(select(Job).where(Job.kind == "process_claim", Job.status == "queued")):
        if (old.payload or {}).get("claim_id") == c.id:
            old.status = "cancelled"
            old.last_error = "superseded by reprocess request"
    n = db.scalar(select(func.count()).select_from(Job).where(Job.kind == "process_claim")) or 0
    enqueue(db, "process_claim", {"claim_id": c.id}, dedupe_key=f"process:{c.id}:{n + 1}")
    audit.record(db, "reprocess_requested", claim_id=c.id, actor=user.actor)
    db.commit()
    return claim_detail(c, user)


@router.post("/claims/{claim_id}/retry-push")
def retry_push(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    require_edit(user)
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "Claim not found")
    if c.status != "push_failed":
        raise HTTPException(409, f"Claim is {c.status}")
    c.status = "approved"
    enqueue(
        db, "push_claim", {"claim_id": c.id, "actor": user.actor}, dedupe_key=f"push:{c.id}:retry:{c.push_attempts}"
    )
    audit.record(db, "push_retry_requested", claim_id=c.id, actor=user.actor)
    db.commit()
    return claim_detail(c, user)


@router.get("/claims/{claim_id}/events")
def claim_events(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    evs = db.scalars(select(AuditEvent).where(AuditEvent.claim_id == claim_id).order_by(AuditEvent.id)).all()
    return {"events": [event_out(e) for e in evs]}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    if not user.can_see_pii:
        raise HTTPException(403, "Original documents contain PII; your role cannot open them")
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    return Response(
        Path(d.storage_path).read_bytes(),
        media_type=d.content_type,
        headers={"Content-Disposition": f'inline; filename="{d.filename}"'},
    )


@router.get("/documents/{doc_id}/pages/{page}.png")
def document_page(
    doc_id: str, page: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    if not user.can_see_pii:
        raise HTTPException(403, "Original documents contain PII; your role cannot open them")
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    data = Path(d.storage_path).read_bytes()
    kind = ocr.sniff_kind(data, d.filename)
    if kind not in ("pdf", "tiff", "png", "jpeg"):
        raise HTTPException(404, "No page images for this document type")
    try:
        png = ocr.render_page_png(data, kind, page)
    except (IndexError, EOFError) as e:
        raise HTTPException(404, "Page out of range") from e
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    rows = db.execute(select(Claim.status, func.count()).group_by(Claim.status)).all()
    by_status = {s: n for s, n in rows}
    claims = db.scalars(select(Claim).where(Claim.decision.is_not(None))).all()
    total = len(claims)
    auto = sum(1 for c in claims if c.decision == "auto_push")
    costs: list[float] = [
        float(c.llm_usage["cost_usd"]) for c in claims if c.llm_usage and c.llm_usage.get("cost_usd") is not None
    ]
    times: list[float] = [float(c.timings_ms["total"]) for c in claims if c.timings_ms and c.timings_ms.get("total")]
    return {
        "by_status": by_status,
        "processed": total,
        "auto_push": auto,
        "review": total - auto,
        "straight_through_rate": round(auto / total, 3) if total else None,
        "total_cost_usd": round(sum(costs), 6) if costs else 0.0,
        "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "avg_processing_ms": int(sum(times) / len(times)) if times else None,
        "queue_depth": db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")),
    }


@router.get("/audit")
def audit_log(
    limit: int = Query(200, le=1000), db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    evs = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all()
    return {"events": [event_out(e) for e in evs]}


# ---------------- settings ----------------
@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    from ..pipeline.llm import PRICING

    return {
        "settings": get_runtime(db),
        "models": sorted(PRICING),
        "providers": ["anthropic", "openai", "azure_openai"],
    }


@router.put("/settings")
def put_settings(body: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    require_admin(user)
    new = update_runtime(db, body)
    audit.record(db, "settings_changed", actor=user.actor, details={"changes": body})
    db.commit()
    return {"settings": new}


# ---------------- integrations ----------------
class IntegrationIn(BaseModel):
    kind: str
    name: str
    base_url: str
    auth_mode: str = "oauth2"
    token_url: str | None = None
    client_id: str | None = None
    secret: str | None = None  # write-only
    scopes: str | None = None
    options: dict[str, Any] = {}
    is_stand_in: bool = False


@router.get("/integrations")
def list_integrations(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "catalog": CLAIMS_CATALOG,
        "integrations": [integration_out(i) for i in db.query(Integration).order_by(Integration.created_at)],
    }


def _apply(i: Integration, body: IntegrationIn) -> None:
    if body.kind not in {c["kind"] for c in CLAIMS_CATALOG}:
        raise HTTPException(400, f"Unknown integration kind {body.kind}")
    i.kind, i.name, i.base_url, i.auth_mode = body.kind, body.name, body.base_url.strip(), body.auth_mode
    i.token_url, i.client_id, i.scopes = body.token_url, body.client_id, body.scopes
    i.options, i.is_stand_in = body.options or {}, body.is_stand_in
    if body.secret:
        try:
            i.secret_encrypted = encrypt_secret(body.secret)
        except SecretsKeyMissing as e:
            raise HTTPException(500, str(e)) from e


@router.post("/integrations")
def create_integration(body: IntegrationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    i = Integration()
    _apply(i, body)
    db.add(i)
    db.flush()
    audit.record(
        db,
        "integration_created",
        actor=user.actor,
        details={"id": i.id, "kind": i.kind, "name": i.name, "base_url": i.base_url},
    )
    db.commit()
    return integration_out(i)


@router.put("/integrations/{iid}")
def update_integration(
    iid: str, body: IntegrationIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    require_admin(user)
    i = db.get(Integration, iid)
    if not i:
        raise HTTPException(404, "Not found")
    _apply(i, body)
    audit.record(db, "integration_updated", actor=user.actor, details={"id": i.id, "secret_rotated": bool(body.secret)})
    db.commit()
    return integration_out(i)


@router.post("/integrations/{iid}/test")
def test_integration(iid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    i = db.get(Integration, iid)
    if not i:
        raise HTTPException(404, "Not found")
    try:
        ok, msg = get_adapter(i).test_connection()
    except SecretsKeyMissing as e:
        ok, msg = False, str(e)
    i.last_tested_at, i.last_test_ok, i.last_test_message = utcnow(), ok, msg
    audit.record(db, "integration_tested", actor=user.actor, details={"id": i.id, "ok": ok, "message": msg})
    db.commit()
    return integration_out(i)


@router.post("/integrations/{iid}/activate")
def activate_integration(iid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    i = db.get(Integration, iid)
    if not i:
        raise HTTPException(404, "Not found")
    if not i.last_test_ok:
        raise HTTPException(409, "Run a successful 'Test connection' before activating")
    for other in db.query(Integration).all():
        other.is_active = other.id == i.id
    audit.record(db, "integration_activated", actor=user.actor, details={"id": i.id, "name": i.name})
    db.commit()
    return integration_out(i)


# ---------------- email connectors ----------------
class EmailConnectorIn(BaseModel):
    kind: str
    name: str
    config: dict[str, Any] = {}
    secret: str | None = None


def _email_out(e: EmailConnector) -> dict[str, Any]:
    return {
        "id": e.id,
        "kind": e.kind,
        "name": e.name,
        "config": e.config,
        "has_secret": bool(e.secret_encrypted),
        "is_active": e.is_active,
        "last_polled_at": e.last_polled_at.isoformat() if e.last_polled_at else None,
        "last_status": e.last_status,
    }


@router.get("/email-connectors")
def list_email(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return {"catalog": EMAIL_CATALOG, "connectors": [_email_out(e) for e in db.query(EmailConnector).all()]}


@router.post("/email-connectors")
def create_email(body: EmailConnectorIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    if body.kind not in {c["kind"] for c in EMAIL_CATALOG}:
        raise HTTPException(400, "Unknown connector kind")
    e = EmailConnector(kind=body.kind, name=body.name, config=body.config)
    if body.secret:
        try:
            e.secret_encrypted = encrypt_secret(body.secret)
        except SecretsKeyMissing as ex:
            raise HTTPException(500, str(ex)) from ex
    db.add(e)
    db.flush()
    audit.record(db, "email_connector_created", actor=user.actor, details={"id": e.id, "kind": e.kind})
    db.commit()
    return _email_out(e)


@router.post("/email-connectors/{eid}/test")
def test_email(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    e = db.get(EmailConnector, eid)
    if not e:
        raise HTTPException(404, "Not found")
    ok, msg = get_source(e).test()
    e.last_status = ("ok: " if ok else "error: ") + msg
    db.commit()
    return {**_email_out(e), "ok": ok, "message": msg}


@router.post("/email-connectors/{eid}/toggle")
def toggle_email(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_admin(user)
    e = db.get(EmailConnector, eid)
    if not e:
        raise HTTPException(404, "Not found")
    e.is_active = not e.is_active
    audit.record(db, "email_connector_toggled", actor=user.actor, details={"id": e.id, "active": e.is_active})
    db.commit()
    return _email_out(e)


@router.post("/email-connectors/{eid}/poll")
def poll_email_now(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_edit(user)
    e = db.get(EmailConnector, eid)
    if not e:
        raise HTTPException(404, "Not found")
    enqueue(
        db,
        "poll_email",
        {"connector_id": e.id},
        dedupe_key=f"poll:{e.id}:manual:{int(utcnow().timestamp())}",
        max_attempts=1,
    )
    db.commit()
    return {"queued": True}


# ---------------- policies (lookup registry) ----------------
@router.get("/policies")
def list_policies(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    from ..security import mask_name, mask_policy

    rows = db.query(Policy).order_by(Policy.policy_number).all()
    return {
        "policies": [
            {
                "policy_number": p.policy_number if user.can_see_pii else mask_policy(p.policy_number),
                "insured_name": p.insured_name if user.can_see_pii else mask_name(p.insured_name),
                "policy_type": p.policy_type,
                "effective_date": p.effective_date.isoformat(),
                "expiration_date": p.expiration_date.isoformat(),
                "status": p.status,
            }
            for p in rows
        ]
    }


# ---------------- evals ----------------
@router.get("/evals")
def list_evals(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    runs = db.query(EvalRun).order_by(EvalRun.id.desc()).limit(20).all()
    return {
        "runs": [
            {"id": r.id, "created_at": r.created_at.isoformat(), "model": r.model, "summary": r.summary} for r in runs
        ]
    }


@router.get("/evals/{run_id}")
def get_eval(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    r = db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "Not found")
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat(),
        "model": r.model,
        "summary": r.summary,
        "cases": r.cases,
    }


@router.post("/evals/run")
def run_evals_api(
    body: dict[str, Any] | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    require_admin(user)
    enqueue(
        db,
        "run_evals",
        {"model": (body or {}).get("model")},
        dedupe_key=f"evals:{int(utcnow().timestamp())}",
        max_attempts=1,
    )
    db.commit()
    return {"queued": True}


__all__ = ["router", "decide"]
