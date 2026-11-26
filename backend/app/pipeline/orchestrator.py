"""The FNOL pipeline: route -> read/OCR -> extract (agent + tools) -> ground -> self-check -> validate -> decide.

Clean claims are pushed automatically; anything uncertain or rule-breaking goes to the human review queue."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..models import Claim, Integration, utcnow
from ..queue import enqueue
from ..schemas import REQUIRED_FIELDS
from ..settings_store import get_runtime
from . import agent
from .llm import Usage
from .router import route_and_read
from .validate import validate


def decide(
    fields: dict[str, Any], issues: list[dict], kind: str, kind_conf: float, cfg: dict[str, Any], has_integration: bool
) -> tuple[str, list[dict[str, Any]]]:
    reasons: list[dict[str, Any]] = []
    thr = float(cfg["confidence_threshold"])
    if kind != "fnol":
        reasons.append({"code": "not_fnol", "message": f"Agent classified this as '{kind}'"})
    elif kind_conf < thr:
        reasons.append({"code": "kind_uncertain", "message": f"Unsure this is an FNOL ({kind_conf:.2f})"})
    for k, f in fields.items():
        present = f.get("value") not in (None, "", [])
        if (k in REQUIRED_FIELDS or present) and f.get("confidence", 0) < thr:
            reasons.append(
                {
                    "code": "low_confidence",
                    "field": k,
                    "message": f"{k} confidence {f.get('confidence', 0):.2f} < {thr:.2f}",
                }
            )
    for i in issues:
        if i["severity"] == "error":
            reasons.append({"code": f"rule:{i['rule']}", "field": i.get("field"), "message": i["message"]})
    if not reasons and not cfg.get("auto_push", True):
        reasons.append({"code": "auto_push_off", "message": "Auto-push is turned off in Settings"})
    if not reasons and not has_integration:
        reasons.append({"code": "no_integration", "message": "No active claims-system integration"})
    return ("review" if reasons else "auto_push"), reasons


def process_claim(db: Session, claim_id: str) -> Claim:
    s = get_settings()
    cfg = get_runtime(db)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"claim {claim_id} not found")
    if claim.status in ("pushed", "pushing") or claim.external_claim_number:
        audit.record(
            db,
            "processing_skipped",
            claim_id=claim.id,
            details={"reason": f"claim already sent ({claim.external_claim_number})"},
        )
        db.commit()
        return claim
    doc = claim.document
    claim.status = "processing"
    claim.error = None
    db.commit()
    timings: dict[str, int] = {}
    usage = Usage(model=cfg["llm_model"], provider=cfg["llm_provider"])
    t_all = time.perf_counter()
    try:
        data = Path(doc.storage_path).read_bytes()
        with audit.trace_step(db, "route_and_read", claim_id=claim.id, document_id=doc.id, timings=timings) as st:
            src = route_and_read(data, doc.filename)
            doc.route, doc.ocr_text, doc.ocr_engine = src.route, src.source_text, src.ocr_engine
            doc.ocr_confidence, doc.page_count = src.ocr_confidence, src.page_count
            st.details = {
                "route": src.route,
                "kind": src.kind,
                "engine": src.ocr_engine,
                "ocr_confidence": src.ocr_confidence,
                "pages": src.page_count,
                "chars": len(src.source_text),
                "sections": src.sections,
            }

        with audit.trace_step(db, "extract", claim_id=claim.id, document_id=doc.id, timings=timings) as st:
            ctx = f"Intake route: {src.route}. OCR mean confidence: {src.ocr_confidence}."
            kind, kconf, fields, res = agent.extract(
                db, src.source_text, cfg["llm_provider"], cfg["llm_model"], s.max_agent_steps, ctx
            )
            usage.add(res.usage)
            st.details = {
                "document_kind": kind,
                "kind_confidence": kconf,
                "tool_calls": [{k: v for k, v in t.items()} for t in res.trace],
                "usage": res.usage.as_dict(),
                "fields": {k: {"value": v["value"], "confidence": v["confidence"]} for k, v in fields.items()},
            }

        with audit.trace_step(db, "ground", claim_id=claim.id, document_id=doc.id, timings=timings) as st:
            changes = agent.ground(fields, src.source_text)
            st.details = {"capped": changes}

        thr = float(cfg["confidence_threshold"])
        low = [
            k
            for k, f in fields.items()
            if f["confidence"] < thr and (k in REQUIRED_FIELDS or f["value"] not in (None, "", []))
        ]
        with audit.trace_step(db, "self_check", claim_id=claim.id, document_id=doc.id, timings=timings) as st:
            sc_changes, sc_usage = agent.self_check(src.source_text, fields, low, cfg["llm_provider"], cfg["llm_model"])
            usage.add(sc_usage)
            st.details = {"rechecked": low, "changes": sc_changes, "usage": sc_usage.as_dict()}

        with audit.trace_step(db, "validate", claim_id=claim.id, document_id=doc.id, timings=timings) as st:
            issues = validate(db, fields, cfg)
            st.details = {"issues": issues}

        active = db.query(Integration).filter(Integration.is_active.is_(True)).first()
        decision, reasons = decide(fields, issues, kind, kconf, cfg, active is not None)
        timings["total"] = int((time.perf_counter() - t_all) * 1000)
        claim.fields = {**fields, "_meta": {"document_kind": kind, "document_kind_confidence": kconf}}
        claim.validation = issues
        claim.review_reasons = reasons
        claim.decision = decision
        claim.llm_usage = usage.as_dict()
        claim.timings_ms = timings
        claim.status = "approved" if decision == "auto_push" else "needs_review"
        audit.record(
            db,
            "decision",
            claim_id=claim.id,
            actor="agent",
            step="decide",
            details={"decision": decision, "reasons": reasons, "usage": usage.as_dict(), "timings_ms": timings},
        )
        if decision == "auto_push":
            enqueue(db, "push_claim", {"claim_id": claim.id}, dedupe_key=f"push:{claim.id}:auto")
        db.commit()
    except Exception as e:
        db.rollback()
        claim = db.get(Claim, claim_id)
        assert claim is not None
        claim.status = "failed"
        claim.error = f"{type(e).__name__}: {e}"[:2000]
        claim.timings_ms = timings
        claim.llm_usage = usage.as_dict()
        audit.record(db, "processing_failed", claim_id=claim.id, details={"error": claim.error})
        db.commit()
        raise
    return claim


def mark_updated(claim: Claim) -> None:
    claim.updated_at = utcnow()
