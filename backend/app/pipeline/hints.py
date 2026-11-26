"""Deterministic scan of source text for facts the extractor often skips in free-text emails."""

from __future__ import annotations

import re
from typing import Any

from .tools import _norm_name, parse_amount

_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}
_SKIP_GIVEN = {
    "dear",
    "hello",
    "hi",
    "thanks",
    "thank",
    "regards",
    "policy",
    "subject",
    "from",
    "date",
    "reported",
    "insured",
    "police",
    "report",
    "total",
    "estimate",
    "estimated",
    "damage",
    "location",
    "intersection",
    "avenue",
    "street",
    "suite",
    "vehicle",
    "toyota",
    "honda",
    "ford",
    "mazda",
    "tesla",
    "chevrolet",
    "chevy",
    "nissan",
    "hyundai",
    "kia",
    "bmw",
    "audi",
    "subaru",
}
_SKIP_LAST = {
    "ave",
    "avenue",
    "street",
    "st",
    "road",
    "rd",
    "blvd",
    "boulevard",
    "lane",
    "ln",
    "drive",
    "dr",
    "way",
    "court",
    "ct",
    "place",
    "pl",
    "insurance",
    "mutual",
    "inc",
    "llc",
    "ltd",
    "company",
    "corp",
    "corporation",
    "camry",
    "civic",
    "accord",
    "corolla",
    "f150",
    "silverado",
    "auto",
    "insurer",
}
_PARTY_CUE = re.compile(
    r"\b(hit|struck|rear-?ended|collided|driver|vehicle|other\s+(?:party|driver|vehicle)|at-?fault|insurer)\b",
    re.I,
)

# $1,450 / USD 1,450.00 / 4,600 dollars — skip things that look like dates or policy numbers.
_AMOUNT = re.compile(
    r"(?:(?<![A-Z])\$\s*|(?<!\w)USD\s*)(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}|\d{2,6})"
    r"|(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})\s*(?:USD|dollars)\b",
    re.I,
)
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}")
_TIME = re.compile(
    r"\b(?:at\s+(?:about\s+|around\s+)?)?((?:[01]?\d|2[0-3]):[0-5]\d)(?:\s*([ap]m))?\b",
    re.I,
)
_REPORT = re.compile(
    r"\b(?:(?:police|fire|incident|department)\s+)?report(?:\s+number)?\s*[:#]?\s*"
    r"([A-Z]{1,5}[-/]?\d{2,4}[-/]\d{3,})\b"
    r"|\b([A-Z]{2,5}-\d{2}-\d{4,})\b",
    re.I,
)
_PERSON = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z']+){1,2})(?:\s*\(([^)]{2,50})\))?")


def _snippet(text: str, start: int, end: int, pad: int = 40) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def _empty(value: Any) -> bool:
    return value in (None, "", [], "None", "none")


def source_hints(text: str, known_names: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Return likely mentions of amounts, times, phones, report numbers and other parties."""
    text = text or ""
    known = {_norm_name(n) for n in (known_names or []) if n}

    amounts: list[dict[str, Any]] = []
    for m in _AMOUNT.finditer(text):
        raw = m.group(1) or m.group(2)
        parsed = parse_amount(m.group(0))
        if not parsed.get("ok"):
            continue
        # Dates like 11/14/2026 and policy-esque numbers should not have been caught;
        # still drop tiny bare integers that are not currency-marked.
        amounts.append(
            {
                "quote": _snippet(text, m.start(), m.end()),
                "amount": parsed["amount"],
                "raw": raw,
                "currency": parsed.get("currency"),
            }
        )

    phones = [{"quote": m.group(0), "value": m.group(0)} for m in _PHONE.finditer(text)]

    times: list[dict[str, Any]] = []
    for m in _TIME.finditer(text):
        hhmm, ampm = m.group(1), (m.group(2) or "").lower()
        h, mi = hhmm.split(":")
        h_i = int(h)
        if ampm == "pm" and h_i < 12:
            h_i += 12
        if ampm == "am" and h_i == 12:
            h_i = 0
        times.append({"quote": _snippet(text, m.start(), m.end(), 16), "value": f"{h_i:02d}:{mi}"})

    reports: list[dict[str, Any]] = []
    for m in _REPORT.finditer(text):
        num = next(g for g in m.groups() if g)
        reports.append({"quote": _snippet(text, m.start(), m.end()), "value": num})

    parties: list[dict[str, Any]] = []
    for m in _PERSON.finditer(text):
        name, org = m.group(1), m.group(2)
        parts = name.split()
        first, last = parts[0].lower(), parts[-1].lower()
        if _norm_name(name) in known or first in _MONTHS or first in _SKIP_GIVEN or last in _SKIP_LAST:
            continue
        window = text[max(0, m.start() - 48) : m.end() + 48]
        if not org and not _PARTY_CUE.search(window):
            continue
        parties.append(
            {
                "name": name,
                "org": org,
                "quote": _snippet(text, m.start(), m.end(), 24),
            }
        )

    return {
        "estimated_amount": amounts,
        "line_items": amounts,
        "insured_phone": phones,
        "loss_time": times,
        "police_report_number": reports,
        "other_parties": parties,
    }


def hint_summary(hints: dict[str, list[dict[str, Any]]]) -> str:
    if not any(hints.values()):
        return ""
    lines = [
        "DETERMINISTIC SCAN (hints only — confirm in the document and copy an exact quote for each value):"
    ]
    if hints.get("estimated_amount"):
        bits = [f"{h['amount']} from '{h['quote']}'" for h in hints["estimated_amount"]]
        lines.append("- amounts: " + "; ".join(bits))
    if hints.get("loss_time"):
        lines.append("- times: " + "; ".join(f"{h['value']} ('{h['quote']}')" for h in hints["loss_time"]))
    if hints.get("insured_phone"):
        lines.append("- phones: " + "; ".join(h["value"] for h in hints["insured_phone"]))
    if hints.get("police_report_number"):
        lines.append("- report numbers: " + "; ".join(h["value"] for h in hints["police_report_number"]))
    if hints.get("other_parties"):
        bits = [f"{h['name']}" + (f" ({h['org']})" if h.get("org") else "") for h in hints["other_parties"]]
        lines.append("- possible other parties: " + "; ".join(bits))
    return "\n".join(lines)


def unfilled_mention_fields(
    fields: dict[str, dict[str, Any]], source_text: str
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Fields that are empty even though the source appears to mention them."""
    known = [
        (fields.get("insured_name") or {}).get("value"),
        (fields.get("reporter_name") or {}).get("value"),
    ]
    hints = source_hints(source_text, [str(n) for n in known if n])
    found: list[tuple[str, list[dict[str, Any]]]] = []
    mention_names = (
        "estimated_amount",
        "other_parties",
        "loss_time",
        "police_report_number",
        "insured_phone",
        "line_items",
    )
    for name in mention_names:
        hits = hints.get(name) or []
        if hits and _empty((fields.get(name) or {}).get("value")):
            found.append((name, hits))
    return found


def fields_to_recheck(
    fields: dict[str, dict[str, Any]],
    source_text: str,
    threshold: float,
    required: list[str],
) -> list[str]:
    """Low-confidence present/required fields, plus empty fields the source still appears to mention."""
    low: list[str] = []
    for k, f in fields.items():
        present = f.get("value") not in (None, "", [])
        if f.get("confidence", 0) < threshold and (k in required or present):
            low.append(k)
    for name, _hits in unfilled_mention_fields(fields, source_text):
        if name not in low:
            low.append(name)
    return low


_FROM = re.compile(r"^From:\s*(.*?)\s*$", re.I | re.M)


def names_from_headers(source_text: str) -> list[str]:
    """Display names on From: lines, so the email sender is not treated as another party."""
    names: list[str] = []
    for m in _FROM.finditer(source_text or ""):
        raw = m.group(1).strip()
        display = raw.split("<", 1)[0].strip().strip('"').strip("'") if raw else ""
        if display and "@" not in display:
            names.append(display)
    return names


def drop_self_parties(fields: dict[str, dict[str, Any]], source_text: str = "") -> list[str]:
    """Remove the insured, the reporter and the email sender from other_parties."""
    skip = {_norm_name((fields.get(k) or {}).get("value")) for k in ("insured_name", "reporter_name")}
    skip.update(_norm_name(n) for n in names_from_headers(source_text))
    skip.discard("")
    parties = (fields.get("other_parties") or {}).get("value") or []
    if not isinstance(parties, list) or not skip:
        return []
    kept, dropped = [], []
    for party in parties:
        name = party.get("name") if isinstance(party, dict) else None
        if name and _norm_name(name) in skip:
            dropped.append(name)
        else:
            kept.append(party)
    if dropped:
        fields["other_parties"]["value"] = kept or None
        notes = list(fields["other_parties"].get("notes") or [])
        notes.append("removed self/sender from other_parties: " + ", ".join(dropped))
        fields["other_parties"]["notes"] = notes
    return dropped
