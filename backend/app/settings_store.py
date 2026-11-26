"""Runtime settings editable from the UI (stored in app_settings), with env defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting
from .schemas import REQUIRED_FIELDS

EDITABLE = {
    "llm_provider": str,
    "llm_model": str,
    "confidence_threshold": float,
    "auto_push": bool,
    "policy_number_regex": str,
    "max_auto_push_amount": float,
    "max_loss_age_days": int,
    "review_if_injuries": bool,
    "date_order": str,
    "blocking_fields": list,
    "review_if_unfilled_mentions": bool,
    "mention_guard_fields": list,
}


def defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "confidence_threshold": s.confidence_threshold,
        "auto_push": s.auto_push,
        "policy_number_regex": r"^[A-Z]{2,4}-\d{6,10}$",
        "max_auto_push_amount": 25000.0,
        "max_loss_age_days": 365,
        "review_if_injuries": True,
        # How the carrier's forms write dates; an extraction that contradicts this reading goes to review.
        "date_order": "month_first",
        # Fields that must clear the confidence threshold before a claim may be sent automatically.
        "blocking_fields": [*REQUIRED_FIELDS, "estimated_amount", "line_items", "other_parties"],
        # If the source mentions an amount or another party but the field was left empty, hold for review.
        "review_if_unfilled_mentions": True,
        "mention_guard_fields": ["estimated_amount", "other_parties"],
    }


def get_runtime(db: Session) -> dict[str, Any]:
    out = defaults()
    for row in db.query(AppSetting).all():
        if row.key in EDITABLE:
            out[row.key] = row.value
    return out


def update_runtime(db: Session, changes: dict[str, Any]) -> dict[str, Any]:
    for k, v in changes.items():
        if k not in EDITABLE or v is None:
            continue
        v = EDITABLE[k](v)
        if k == "date_order" and v not in ("month_first", "day_first"):
            raise ValueError("date_order must be month_first or day_first")
        row = db.get(AppSetting, k)
        if row:
            row.value = v
        else:
            db.add(AppSetting(key=k, value=v))
    db.flush()
    return get_runtime(db)
