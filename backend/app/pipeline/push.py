"""Push approved claims to the active claims system, exactly once."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import audit
from ..integrations.base import PushError
from ..integrations.registry import get_adapter
from ..models import Claim, Integration, utcnow


class NotPushable(RuntimeError):
    pass


def push_claim(db: Session, claim_id: str, actor: str = "system") -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise NotPushable("claim not found")
    if claim.status == "pushed" and claim.external_claim_number:
        audit.record(
            db,
            "push_skipped_duplicate",
            claim_id=claim.id,
            actor=actor,
            details={"external_claim_number": claim.external_claim_number},
        )
        db.commit()
        return claim
    if claim.status not in ("approved", "push_failed", "pushing"):
        raise NotPushable(f"claim status is {claim.status}; only approved claims can be pushed")
    integ = db.query(Integration).filter(Integration.is_active.is_(True)).first()
    if integ is None:
        raise NotPushable("no active integration")
    adapter = get_adapter(integ)
    claim.status = "pushing"
    claim.push_attempts += 1
    claim.external_system = integ.kind
    db.commit()

    state: dict[str, Any] = dict(claim.push_state or {})

    def checkpoint(st: dict[str, Any]) -> None:
        claim.push_state = dict(st)
        flag_modified(claim, "push_state")
        db.commit()

    fields = {k: v for k, v in (claim.fields or {}).items() if not k.startswith("_")}
    try:
        res = adapter.push(fields, claim.push_key, state, checkpoint, claim.reference)
    except PushError as e:
        claim.status = "push_failed"
        claim.error = str(e)
        audit.record(
            db,
            "push_failed",
            claim_id=claim.id,
            actor=actor,
            step="push",
            details={
                "system": integ.kind,
                "error": str(e),
                "retryable": e.retryable,
                "calls": _calls(adapter.calls),
                "attempt": claim.push_attempts,
            },
        )
        db.commit()
        raise
    claim.status = "pushed"
    claim.error = None
    claim.external_claim_id = res.external_id
    claim.external_claim_number = res.claim_number
    claim.pushed_at = utcnow()
    audit.record(
        db,
        "pushed",
        claim_id=claim.id,
        actor=actor,
        step="push",
        details={
            "system": integ.kind,
            "integration": integ.name,
            "stand_in": integ.is_stand_in,
            "external_claim_id": res.external_id,
            "external_claim_number": res.claim_number,
            "state": res.state,
            "calls": _calls(adapter.calls),
            "attempt": claim.push_attempts,
        },
    )
    db.commit()
    return claim


def _calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"method": c["method"], "url": c["url"], "status": c["status"]} for c in calls]
