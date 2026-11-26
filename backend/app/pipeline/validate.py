"""Guardrails: schema checks + business rules. Errors block auto-push; warnings are shown to adjusters."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ..schemas import FIELD_SPECS, REQUIRED_FIELDS, Party
from . import hints as H
from . import tools as T


def _v(fields: dict[str, Any], k: str) -> Any:
    f = fields.get(k) or {}
    return f.get("value") if isinstance(f, dict) else None


def _issue(rule: str, message: str, field: str | None = None, severity: str = "error") -> dict[str, Any]:
    return {"rule": rule, "field": field, "severity": severity, "message": message}


def validate(
    db: Session,
    fields: dict[str, Any],
    cfg: dict[str, Any],
    today: date | None = None,
    source_text: str = "",
) -> list[dict]:
    today = today or date.today()
    issues: list[dict[str, Any]] = []

    for k in REQUIRED_FIELDS:
        v = _v(fields, k)
        if v is None or (isinstance(v, str) and not v.strip()):
            issues.append(_issue("required", f"{k} is required for submission", k))

    # schema / type checks
    for k, spec in FIELD_SPECS.items():
        v = _v(fields, k)
        if v is None:
            continue
        if "enum" in spec and v not in spec["enum"]:
            issues.append(_issue("schema", f"{k} must be one of {spec['enum']}", k))
        if spec["type"] == "number" and not isinstance(v, int | float):
            issues.append(_issue("schema", f"{k} must be a number", k))
        if spec["type"] == "boolean" and not isinstance(v, bool):
            issues.append(_issue("schema", f"{k} must be true/false", k))
    parties = _v(fields, "other_parties")
    if parties is not None:
        try:
            [Party(**p) for p in parties]
        except Exception as e:
            issues.append(_issue("schema", f"other_parties malformed: {e}", "other_parties"))

    # policy number format + in force
    pn = _v(fields, "policy_number")
    loss_date_s = _v(fields, "loss_date")
    loss_d: date | None = None
    if loss_date_s:
        try:
            loss_d = date.fromisoformat(str(loss_date_s))
        except ValueError:
            issues.append(_issue("loss_date_format", "loss_date must be an ISO date (YYYY-MM-DD)", "loss_date"))
    if pn:
        if not re.match(cfg.get("policy_number_regex") or r".+", str(pn)):
            issues.append(
                _issue("policy_format", f"Policy number '{pn}' does not match the carrier format", "policy_number")
            )
        pol = T.lookup_policy(db, str(pn), loss_d.isoformat() if loss_d else None)
        if not pol.get("found"):
            issues.append(_issue("policy_exists", "Policy not found in policy admin system", "policy_number"))
        elif pol.get("in_force_on_loss_date") is False:
            issues.append(
                _issue(
                    "policy_in_force",
                    f"Policy not in force on loss date (term {pol['effective_date']} to "
                    f"{pol['expiration_date']}, status {pol['status']})",
                    "policy_number",
                )
            )
        else:
            ins = _v(fields, "insured_name")
            if ins and pol.get("insured_name") and T._norm_name(ins) != T._norm_name(pol["insured_name"]):
                issues.append(
                    _issue(
                        "insured_matches_policy",
                        "Insured name differs from the policy's named insured",
                        "insured_name",
                        "warning",
                    )
                )
            lob = _v(fields, "line_of_business")
            expected = {
                "PersonalAuto": "auto",
                "Homeowners": "property",
                "CommercialProperty": "property",
                "GeneralLiability": "liability",
            }.get(pol.get("policy_type", ""))
            if lob and expected and lob != expected:
                issues.append(
                    _issue(
                        "lob_matches_policy",
                        f"Line of business '{lob}' does not match policy type {pol['policy_type']}",
                        "line_of_business",
                        "warning",
                    )
                )

    if loss_d:
        quote = (fields.get("loss_date") or {}).get("source") or ""
        parsed = T.parse_date(quote, today) if quote else {}
        if parsed.get("ambiguous"):
            order = cfg.get("date_order", "month_first")
            expected = parsed["alternatives"][order]
            if expected != loss_d.isoformat():
                issues.append(
                    _issue(
                        "loss_date_ambiguous",
                        f"Loss date written as '{quote.strip()}' reads as {expected} on this carrier's "
                        f"{order.replace('_', '-')} forms, but {loss_d.isoformat()} was extracted. "
                        "Confirm with the reporter.",
                        "loss_date",
                    )
                )
        if loss_d > today:
            issues.append(_issue("loss_date_not_future", "Loss date is in the future", "loss_date"))
        elif (today - loss_d).days > int(cfg.get("max_loss_age_days", 365)):
            issues.append(
                _issue(
                    "loss_date_age",
                    f"Loss reported more than {cfg.get('max_loss_age_days')} days after it happened (late notice)",
                    "loss_date",
                    "warning",
                )
            )

    amt = _v(fields, "estimated_amount")
    items = _v(fields, "line_items") or []
    if amt is not None and isinstance(amt, int | float):
        if amt < 0:
            issues.append(_issue("amount_positive", "Estimated amount cannot be negative", "estimated_amount"))
        if items:
            total = T.sum_amounts([float(i.get("amount", 0)) for i in items if isinstance(i, dict)])["total"]
            if abs(total - float(amt)) > 0.01:
                issues.append(
                    _issue(
                        "amounts_consistent",
                        f"Line items add up to {total:,.2f} but estimated total is {float(amt):,.2f}",
                        "estimated_amount",
                    )
                )
        if float(amt) > float(cfg.get("max_auto_push_amount", 25000)):
            issues.append(
                _issue(
                    "amount_authority",
                    f"Amount {float(amt):,.2f} exceeds the auto-push authority limit "
                    f"{float(cfg.get('max_auto_push_amount', 25000)):,.2f}",
                    "estimated_amount",
                )
            )

    if cfg.get("review_if_injuries", True) and _v(fields, "injuries") is True:
        issues.append(_issue("injury_review", "Bodily injury reported: adjuster review required", "injuries"))

    if cfg.get("review_if_unfilled_mentions", True) and source_text:
        mention_fields = cfg.get("mention_guard_fields") or ["estimated_amount", "other_parties"]
        for name, hits in H.unfilled_mention_fields(fields, source_text):
            if name not in mention_fields:
                continue
            quotes = "; ".join({(h.get("quote") or h.get("value") or h.get("name") or "")[:80] for h in hits})
            if name == "estimated_amount":
                issues.append(
                    _issue(
                        "unfilled_amount_in_source",
                        "The source mentions an amount "
                        f"({quotes}) but estimated_amount was left empty. Confirm the total before sending.",
                        "estimated_amount",
                    )
                )
            elif name == "other_parties":
                names = ", ".join(sorted({h.get("name") or "" for h in hits if h.get("name")}))
                issues.append(
                    _issue(
                        "unfilled_party_in_source",
                        f"The source names another party ({names}) but other_parties was left empty. "
                        "Confirm who was involved before sending.",
                        "other_parties",
                    )
                )

    return issues
