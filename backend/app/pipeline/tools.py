"""Deterministic tools the extraction agent can call instead of guessing."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as dparser
from sqlalchemy.orm import Session

from ..models import Policy

CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "₦": "NGN", "C$": "CAD", "A$": "AUD"}


def normalize_policy_number(p: str) -> str:
    return re.sub(r"\s+", "", p or "").upper()


def lookup_policy(db: Session, policy_number: str, loss_date: str | None = None) -> dict[str, Any]:
    pn = normalize_policy_number(policy_number)
    pol = db.get(Policy, pn)
    if pol is None:
        # tolerate OCR confusions O/0 and I/1 in the numeric part
        alt = re.sub(
            r"(?<=-)([0-9OIl]+)$", lambda m: m.group(1).replace("O", "0").replace("I", "1").replace("l", "1"), pn
        )
        pol = db.get(Policy, alt) if alt != pn else None
        if pol is None:
            return {"found": False, "policy_number": pn, "message": "No policy with this number"}
    res: dict[str, Any] = {
        "found": True,
        "policy_number": pol.policy_number,
        "insured_name": pol.insured_name,
        "policy_type": pol.policy_type,
        "effective_date": pol.effective_date.isoformat(),
        "expiration_date": pol.expiration_date.isoformat(),
        "status": pol.status,
    }
    if pol.policy_number != pn:
        res["note"] = f"Matched after correcting likely OCR confusion ({pn} -> {pol.policy_number})"
    if loss_date:
        try:
            d = date.fromisoformat(loss_date)
            res["in_force_on_loss_date"] = pol.status == "inforce" and pol.effective_date <= d <= pol.expiration_date
        except ValueError:
            res["in_force_on_loss_date"] = None
    return res


def parse_date(text: str, today: date | None = None) -> dict[str, Any]:
    """Parse a written date. Flags ambiguity (e.g. 03/04/2026) and returns both readings."""
    today = today or date.today()
    t = (text or "").strip()
    if not t:
        return {"ok": False, "error": "empty"}
    try:
        us = dparser.parse(t, dayfirst=False, fuzzy=True)
    except (ValueError, OverflowError):
        return {"ok": False, "error": f"Could not parse '{t}'"}
    out: dict[str, Any] = {"ok": True, "iso": us.date().isoformat(), "ambiguous": False}
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", t)
    if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2):
        eu = dparser.parse(t, dayfirst=True, fuzzy=True).date()
        out["ambiguous"] = True
        out["alternatives"] = {"month_first": us.date().isoformat(), "day_first": eu.isoformat()}
    out["in_future"] = us.date() > today
    return out


def parse_amount(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    cur = None
    for sym, code in sorted(CURRENCY_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if sym in t:
            cur = code
            break
    m3 = re.search(r"\b(USD|GBP|EUR|NGN|CAD|AUD)\b", t, re.I)
    if m3:
        cur = m3.group(1).upper()
    num = re.search(r"-?\d[\d,]*(?:\.\d+)?|\.\d+", t)
    if not num:
        return {"ok": False, "error": f"No amount in '{t}'"}
    raw = num.group(0).replace(",", "")
    mult = 1
    if re.search(r"\d\s*[kK]\b", t):
        mult = 1000
    try:
        val = Decimal(raw) * mult
    except InvalidOperation:
        return {"ok": False, "error": f"Bad number '{raw}'"}
    return {"ok": True, "amount": float(round(val, 2)), "currency": cur}


def sum_amounts(amounts: list[float]) -> dict[str, Any]:
    total = sum((Decimal(str(a)) for a in amounts), Decimal(0))
    return {"ok": True, "total": float(round(total, 2)), "count": len(amounts)}


def _norm_name(n: str) -> str:
    parts = re.sub(r"[^a-z ]", " ", (n or "").lower()).split()
    return " ".join(sorted(p for p in parts if len(p) > 1))
