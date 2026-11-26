"""Tool-using extraction agent + self-check pass.

1. extract(): the model reads the source text, may call lookup_policy / parse_date / parse_amount / sum_amounts,
   then calls submit_extraction with {document_kind, fields:{name:{value, confidence, source}}}.
2. ground(): deterministic check that each quote really appears in the source; ungrounded => confidence capped.
3. self_check(): fields still below the threshold are re-read by the model with a focused prompt.
"""

from __future__ import annotations

import json
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from ..schemas import FIELD_SPECS, field_json_schema
from . import hints as H
from . import tools as T
from .llm import LoopResult, ToolSpec, Usage, get_provider

SYSTEM = """You are the FNOL (First Notice of Loss) intake agent for a property & casualty insurance carrier.
You read one incoming item (a scanned claim form after OCR, a typed PDF, or a free-text email, possibly with
attachments) and extract structured claim data for the claims system.

Rules:
- Only use information in the document or returned by tools. Never invent values. If a field is absent, set
  value null, source null and confidence to how sure you are that it is truly absent.
- "source" must be an exact, short quote copied from the document (OCR errors included) that supports the value.
- Confidence is a calibrated probability (0-1) that the value is correct. Lower it for OCR noise, handwriting
  artefacts, conflicting statements, ambiguous dates, or values you had to infer.
- Call lookup_policy with the policy number (and loss date if known) to verify it exists and is in force.
  If the tool corrects an OCR confusion, use the corrected number and say so via a lower confidence (<=0.8).
- Use parse_date for any date that is not already ISO, and parse_amount / sum_amounts for money. If a date
  is ambiguous (e.g. 03/04/2026) and the document gives no locale hint, pick US month-first and set
  confidence <= 0.6.
- loss_date is the date the loss happened, not the date reported or the form date.
- estimated_amount is the total claimed/estimated damage. line_items lists itemised amounts if present.
- For free-text emails and unstructured narratives, go through the body systematically and extract:
  the loss time, every money amount (itemised line_items plus the stated total as estimated_amount;
  call parse_amount and sum_amounts), police or fire report numbers, phone numbers, and every other
  person or company named besides the insured (other_parties, with a role such as driver). If the
  reporter is the insured, a phone next to "reported by" is insured_phone as well.
- A "DETERMINISTIC SCAN" section may be attached; treat it as hints only and still copy quotes from
  the document itself.
- document_kind: "fnol" for a new loss report, "claim_followup" for updates on an existing claim,
  "not_claim" for anything else (newsletters, spam, quotes).
- Today's date is {today}. Then call submit_extraction exactly once."""


def _tool_specs(db: Session) -> list[ToolSpec]:
    return [
        ToolSpec(
            "lookup_policy",
            "Look up a policy in the policy admin system. Returns insured name, type, term and in-force status.",
            {
                "type": "object",
                "properties": {
                    "policy_number": {"type": "string"},
                    "loss_date": {"type": "string", "description": "ISO date"},
                },
                "required": ["policy_number"],
            },
            lambda a: T.lookup_policy(db, a.get("policy_number", ""), a.get("loss_date")),
        ),
        ToolSpec(
            "parse_date",
            "Parse a date as written in the document. Flags ambiguous day/month order and future dates.",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            lambda a: T.parse_date(a.get("text", "")),
        ),
        ToolSpec(
            "parse_amount",
            "Parse a money amount as written (e.g. '$4,250.00', '4.2k USD').",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            lambda a: T.parse_amount(a.get("text", "")),
        ),
        ToolSpec(
            "sum_amounts",
            "Add up a list of amounts exactly (use for line items vs total).",
            {
                "type": "object",
                "properties": {"amounts": {"type": "array", "items": {"type": "number"}}},
                "required": ["amounts"],
            },
            lambda a: T.sum_amounts([float(x) for x in a.get("amounts", [])]),
        ),
        ToolSpec(
            "submit_extraction",
            "Submit the final structured FNOL extraction. Call exactly once.",
            {
                "type": "object",
                "properties": {
                    "document_kind": {"type": "string", "enum": ["fnol", "claim_followup", "not_claim"]},
                    "document_kind_confidence": {"type": "number"},
                    "fields": field_json_schema(),
                },
                "required": ["document_kind", "document_kind_confidence", "fields"],
            },
        ),
    ]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def quote_found(quote: str | None, source: str) -> float:
    """Best fuzzy match ratio of the quote inside the source (1.0 = verbatim)."""
    if not quote:
        return 0.0
    q, src = _norm(quote), _norm(source)
    if not q:
        return 0.0
    if q in src:
        return 1.0
    best = 0.0
    n = len(q)
    step = max(1, n // 4)
    for i in range(0, max(1, len(src) - n + 1), step):
        r = SequenceMatcher(None, q, src[i : i + n + 10]).ratio()
        if r > best:
            best = r
            if best > 0.95:
                break
    return round(best, 3)


def _as_dict(v: Any) -> dict[str, Any]:
    """Models occasionally return a nested object as a JSON string; accept both."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            return {}
    return v if isinstance(v, dict) else {}


_ROLES = {"insured", "claimant", "third_party", "witness", "driver", "other"}


def _coerce_roles(parties: list[Any]) -> tuple[list[Any], list[str]]:
    """The model sometimes invents a role (e.g. 'agent'): map it to 'other' and note it instead of failing."""
    notes: list[str] = []
    fixed: list[Any] = []
    for p in parties:
        if isinstance(p, dict) and p.get("role") not in _ROLES:
            notes.append(f"role '{p.get('role')}' for {p.get('name')} is not a known role; stored as 'other'")
            p = {**p, "role": "other"}
        fixed.append(p)
    return fixed, notes


def coerce_fields(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in FIELD_SPECS:
        f = raw.get(name) or {}
        if not isinstance(f, dict):
            f = {"value": f, "confidence": 0.5, "source": None}
        try:
            conf = float(f.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        value = f.get("value")
        notes: list[str] = []
        if name == "other_parties" and isinstance(value, list):
            value, notes = _coerce_roles(value)
        out[name] = {
            "value": value,
            "confidence": max(0.0, min(1.0, conf)),
            "source": f.get("source"),
            "method": "llm",
            "notes": notes,
        }
    return out


def ground(fields: dict[str, dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    """Cap confidence of values whose quote cannot be found in the source text."""
    changes = []
    for name, f in fields.items():
        if f["value"] in (None, "", []) or name in (
            "injuries",
            "line_of_business",
            "loss_cause",
            "currency",
            "document_kind",
        ):
            continue
        score = quote_found(f.get("source"), source_text)
        f["grounding"] = score
        problem = None
        if score < 0.75:
            problem = f"quote not found in source (match {score:.2f})"
        else:
            problem = value_matches_quote(name, f["value"], f.get("source") or "")
        if problem:
            old = f["confidence"]
            f["confidence"] = min(old, 0.5)
            f["notes"].append(problem)
            changes.append(
                {
                    "field": name,
                    "grounding": score,
                    "problem": problem,
                    "confidence_before": old,
                    "confidence_after": f["confidence"],
                }
            )
    return changes


def value_matches_quote(name: str, value: Any, quote: str) -> str | None:
    """Check the value actually follows from its own quote (catches 'right quote, wrong number')."""
    if name == "estimated_amount":
        parsed = T.parse_amount(quote)
        try:
            if parsed.get("ok") and abs(float(parsed["amount"]) - float(value)) > 0.01:
                return f"value {value} differs from quoted amount {parsed['amount']}"
        except (TypeError, ValueError):
            return "amount is not a number"
    if name == "loss_date":
        parsed = T.parse_date(quote)
        if parsed.get("ok"):
            options = {parsed["iso"], *(parsed.get("alternatives") or {}).values()}
            if str(value) not in options and re.search(r"\d", quote):
                return f"value {value} differs from quoted date ({parsed['iso']})"
    if name == "policy_number":
        v = re.sub(r"[^A-Z0-9]", "", str(value).upper())
        q = re.sub(r"[^A-Z0-9]", "", quote.upper())
        if v and v not in q:
            return "policy number differs from the quote (possible OCR correction)"
    return None


def extract(
    db: Session, source_text: str, provider: str, model: str, max_steps: int, context: str = ""
) -> tuple[str, float, dict[str, dict[str, Any]], LoopResult]:
    llm = get_provider(provider, model)
    known: list[str] = H.names_from_headers(source_text)
    scan = H.hint_summary(H.source_hints(source_text, known))
    user = (f"{context}\n\n" if context else "")
    if scan:
        user += scan + "\n\n"
    user += "DOCUMENT TEXT (OCR/parsed):\n<<<\n" + source_text[:60000] + "\n>>>"
    res = llm.run_tools(
        SYSTEM.replace("{today}", date.today().isoformat()), user, _tool_specs(db), "submit_extraction", max_steps
    )
    fi = res.final_input
    fields = coerce_fields(_as_dict(fi.get("fields")))
    H.drop_self_parties(fields, source_text)
    kind = fi.get("document_kind") or "fnol"
    kconf = float(fi.get("document_kind_confidence") or 0.0)
    return kind, kconf, fields, res


VERIFY_SYSTEM = """You are a meticulous claims QA reviewer. Some extracted FNOL fields were flagged as
low-confidence. Re-read the document carefully and, for each listed field, return the correct value, a
calibrated confidence and an exact supporting quote from the document. Keep the value if it was right. If the
document does not contain it, return null. Empty fields are included when a deterministic scan of the
source suggests the fact is present — fill them if the document supports them. Today's date is {today}.
Call submit_verification once."""


def self_check(
    source_text: str, fields: dict[str, dict[str, Any]], low: list[str], provider: str, model: str
) -> tuple[list[dict[str, Any]], Usage]:
    if not low:
        return [], Usage(model=model, provider=provider)
    llm = get_provider(provider, model)
    full = field_json_schema()["properties"]
    schema = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "properties": {
                    k: {**full[k], "properties": {**full[k]["properties"], "reason": {"type": "string"}}} for k in low
                },
                "required": low,
            }
        },
        "required": ["fields"],
    }
    listing = "\n".join(
        f"- {k} ({FIELD_SPECS[k]['desc']}): current value={fields[k]['value']!r}, confidence={fields[k]['confidence']},"
        f" quote={fields[k].get('source')!r}, notes={fields[k].get('notes')}"
        for k in low
    )
    user = f"FLAGGED FIELDS:\n{listing}\n\nDOCUMENT TEXT:\n<<<\n{source_text[:60000]}\n>>>"
    res = llm.run_tools(
        VERIFY_SYSTEM.replace("{today}", date.today().isoformat()),
        user,
        [ToolSpec("submit_verification", "Submit verified values for the flagged fields.", schema)],
        "submit_verification",
        1,
    )
    got = _as_dict(res.final_input.get("fields"))
    changes = []
    for k in low:
        v = got.get(k)
        if not isinstance(v, dict):
            continue
        before = dict(fields[k])
        new_val = v.get("value")
        new_conf = float(v.get("confidence") or 0)
        new_src = v.get("source")
        if k not in ("injuries", "line_of_business", "loss_cause", "currency") and new_val not in (None, "", []):
            g = quote_found(new_src, source_text)
            if g < 0.75:
                new_conf = min(new_conf, 0.5)
        fields[k].update(
            {"value": new_val, "confidence": max(0.0, min(1.0, new_conf)), "source": new_src, "method": "self_check"}
        )
        if k == "other_parties":
            coerced, role_notes = _coerce_roles(new_val if isinstance(new_val, list) else [])
            fields[k]["value"] = coerced
            new_val = coerced
        notes = [*before.get("notes", []), f"self-check: {v.get('reason', '')}".strip()]
        if k == "other_parties":
            notes.extend(role_notes)
        fields[k]["notes"] = notes
        changes.append(
            {
                "field": k,
                "value_changed": before["value"] != new_val,
                "confidence_before": before["confidence"],
                "confidence_after": fields[k]["confidence"],
            }
        )
    H.drop_self_parties(fields, source_text)
    return changes, res.usage
