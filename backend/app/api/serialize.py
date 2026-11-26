from __future__ import annotations

from typing import Any

from ..models import AuditEvent, Claim, Integration
from ..security import mask_fields, mask_obj, mask_text
from .deps import User


def claim_summary(c: Claim, user: User) -> dict[str, Any]:
    f = c.fields or {}
    pf = {k: v for k, v in f.items() if not k.startswith("_")}
    shown = pf if user.can_see_pii else mask_fields(pf)

    def v(k: str) -> Any:
        return (shown.get(k) or {}).get("value")

    confs = [
        x.get("confidence", 0) for x in pf.values() if isinstance(x, dict) and x.get("value") not in (None, "", [])
    ]
    return {
        "id": c.id,
        "reference": c.reference,
        "status": c.status,
        "decision": c.decision,
        "policy_number": v("policy_number"),
        "insured_name": v("insured_name"),
        "loss_date": v("loss_date"),
        "loss_cause": v("loss_cause"),
        "estimated_amount": v("estimated_amount"),
        "currency": v("currency"),
        "min_confidence": round(min(confs), 2) if confs else None,
        "review_reason_count": len(c.review_reasons or []),
        "route": c.document.route if c.document else None,
        "source": c.document.source if c.document else None,
        "filename": c.document.filename if c.document else None,
        "external_claim_number": c.external_claim_number,
        "external_system": c.external_system,
        "cost_usd": (c.llm_usage or {}).get("cost_usd"),
        "total_ms": (c.timings_ms or {}).get("total"),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def claim_detail(c: Claim, user: User) -> dict[str, Any]:
    f = dict(c.fields or {})
    meta = f.pop("_meta", {})
    d = c.document
    return {
        **claim_summary(c, user),
        "fields": f if user.can_see_pii else mask_fields(f),
        "meta": meta,
        "validation": c.validation,
        "review_reasons": c.review_reasons,
        "llm_usage": c.llm_usage,
        "timings_ms": c.timings_ms,
        "error": c.error,
        "reviewed_by": c.reviewed_by,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "reject_reason": c.reject_reason,
        "external_claim_id": c.external_claim_id,
        "push_attempts": c.push_attempts,
        "pushed_at": c.pushed_at.isoformat() if c.pushed_at else None,
        "pii_masked": not user.can_see_pii,
        "document": {
            "id": d.id,
            "filename": d.filename,
            "content_type": d.content_type,
            "route": d.route,
            "ocr_engine": d.ocr_engine,
            "ocr_confidence": d.ocr_confidence,
            "page_count": d.page_count,
            "source": d.source,
            "email_subject": d.email_subject,
            "email_from": d.email_from if user.can_see_pii else mask_text(d.email_from),
            "text": d.ocr_text if user.can_see_pii else mask_text(d.ocr_text),
            "size_bytes": d.size_bytes,
        }
        if d
        else None,
    }


def event_out(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
        "actor": e.actor,
        "event_type": e.event_type,
        "step": e.step,
        "duration_ms": e.duration_ms,
        "details": mask_obj(e.details),
    }


def integration_out(i: Integration) -> dict[str, Any]:
    return {
        "id": i.id,
        "kind": i.kind,
        "name": i.name,
        "base_url": i.base_url,
        "auth_mode": i.auth_mode,
        "token_url": i.token_url,
        "client_id": i.client_id,
        "scopes": i.scopes,
        "options": i.options,
        "has_secret": bool(i.secret_encrypted),
        "is_active": i.is_active,
        "is_stand_in": i.is_stand_in,
        "last_tested_at": i.last_tested_at.isoformat() if i.last_tested_at else None,
        "last_test_ok": i.last_test_ok,
        "last_test_message": i.last_test_message,
    }
