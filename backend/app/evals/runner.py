"""Run the pipeline over the labelled SAMPLE set and score per-field accuracy, routing and decisions.

  python -m app.evals.runner [--model claude-haiku-5-5]
Results are stored in eval_runs and written to samples/eval/results/<timestamp>.json."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import EvalRun
from ..pipeline import agent
from ..pipeline.llm import Usage
from ..pipeline.orchestrator import decide
from ..pipeline.router import route_and_read
from ..pipeline.validate import validate
from ..schemas import REQUIRED_FIELDS
from ..settings_store import get_runtime

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "samples" / "eval"
SCORED = [
    "policy_number",
    "line_of_business",
    "loss_date",
    "loss_cause",
    "loss_location",
    "insured_name",
    "reporter_name",
    "other_parties",
    "police_report_number",
    "injuries",
    "estimated_amount",
]


def _n(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _tokens(s: Any) -> set[str]:
    return {t for t in _n(s).split() if len(t) > 1}


def field_correct(name: str, got: Any, want: Any) -> bool:
    if name == "other_parties":
        names = {_n(p.get("name")) for p in (got or []) if isinstance(p, dict)}
        return all(any(_n(w) in n or n in _n(w) for n in names if n) for w in want)  # recall of expected names
    if want is None:
        return got in (None, "", [], "None", "none", "N/A")
    if name == "estimated_amount":
        try:
            return abs(float(got) - float(want)) < 0.01
        except (TypeError, ValueError):
            return False
    if name == "injuries":
        return got is want
    if name == "loss_location":
        w, g = _tokens(want), _tokens(got)
        return bool(w) and len(w & g) / len(w) >= 0.6
    if name in ("insured_name", "reporter_name"):
        return _tokens(want) <= _tokens(got) or _tokens(got) == _tokens(want)
    return _n(got) == _n(want)


def run_evals(
    db: Session, model: str | None = None, provider: str | None = None, only: list[str] | None = None
) -> EvalRun:
    cfg = get_runtime(db)
    model = model or cfg["llm_model"]
    provider = provider or cfg["llm_provider"]
    labels = json.loads((EVAL_DIR / "labels.json").read_text())
    if only:
        labels = [lab for lab in labels if lab["id"] in only]
    has_integ = True  # evals score the decision as if a claims system were connected
    cases = []
    total_usage = Usage(model=model, provider=provider)
    for lab in labels:
        data = (EVAL_DIR / "files" / lab["file"]).read_bytes()
        t0 = time.perf_counter()
        src = route_and_read(data, lab["file"])
        t_ocr = time.perf_counter() - t0
        kind, kconf, fields, res = agent.extract(
            db,
            src.source_text,
            provider,
            model,
            get_settings().max_agent_steps,
            f"Intake route: {src.route}. OCR mean confidence: {src.ocr_confidence}.",
        )
        usage = res.usage
        before = {k: v["value"] for k, v in fields.items()}
        agent.ground(fields, src.source_text)
        thr = float(cfg["confidence_threshold"])
        low = [
            k
            for k, f in fields.items()
            if f["confidence"] < thr and (k in REQUIRED_FIELDS or f["value"] not in (None, "", []))
        ]
        _, sc_usage = agent.self_check(src.source_text, fields, low, provider, model)
        usage.add(sc_usage)
        issues = validate(db, fields, cfg)
        decision, reasons = decide(fields, issues, kind, kconf, cfg, has_integ)
        elapsed = time.perf_counter() - t0
        total_usage.add(usage)
        per_field = {}
        per_field_first_pass = {}
        if lab["expect_kind"] == "fnol":
            for k in SCORED:
                want = lab["expect"].get(k)
                per_field[k] = field_correct(k, fields[k]["value"], want)
                per_field_first_pass[k] = field_correct(k, before[k], want)
        cases.append(
            {
                "id": lab["id"],
                "format": lab["format"],
                "route": src.route,
                "ocr_confidence": src.ocr_confidence,
                "kind": kind,
                "kind_ok": kind == lab["expect_kind"],
                "decision": decision,
                "expect_decision": lab["expect_decision"],
                "decision_ok": decision == lab["expect_decision"],
                "reasons": [r["code"] for r in reasons],
                "self_checked": low,
                "fields_ok": per_field,
                "fields_ok_first_pass": per_field_first_pass,
                "values": {k: fields[k]["value"] for k in SCORED},
                "confidence": {k: fields[k]["confidence"] for k in SCORED},
                "latency_s": round(elapsed, 2),
                "ocr_s": round(t_ocr, 2),
                "usage": usage.as_dict(),
            }
        )
        print(
            f"{lab['id']:34s} route={src.route:22s} kind={kind:14s} decision={decision:9s} "
            f"(want {lab['expect_decision']}) fields={sum(per_field.values())}/{len(per_field)} "
            f"{elapsed:.1f}s ${usage.cost_usd}",
            flush=True,
        )

    scored = [c for c in cases if c["fields_ok"]]
    field_acc = {k: round(sum(c["fields_ok"][k] for c in scored) / len(scored), 3) for k in SCORED} if scored else {}
    first_acc = (
        {k: round(sum(c["fields_ok_first_pass"][k] for c in scored) / len(scored), 3) for k in SCORED} if scored else {}
    )
    n_fields = sum(len(c["fields_ok"]) for c in scored)
    auto = [c for c in cases if c["decision"] == "auto_push"]
    summary = {
        "model": model,
        "provider": provider,
        "cases": len(cases),
        "field_accuracy": field_acc,
        "field_accuracy_before_self_check": first_acc,
        "overall_field_accuracy": round(sum(sum(c["fields_ok"].values()) for c in scored) / n_fields, 3)
        if n_fields
        else None,
        "doc_kind_accuracy": round(sum(c["kind_ok"] for c in cases) / len(cases), 3),
        "decision_accuracy": round(sum(c["decision_ok"] for c in cases) / len(cases), 3),
        "auto_push_count": len(auto),
        "auto_push_precision": round(sum(c["expect_decision"] == "auto_push" for c in auto) / len(auto), 3)
        if auto
        else None,
        "unsafe_auto_push": [c["id"] for c in auto if c["expect_decision"] != "auto_push"],
        "perfect_auto_push_cases": [c["id"] for c in auto if all(c["fields_ok"].values())],
        "total_cost_usd": total_usage.cost_usd,
        "input_tokens": total_usage.input_tokens,
        "output_tokens": total_usage.output_tokens,
        "llm_calls": total_usage.calls,
        "avg_latency_s": round(sum(c["latency_s"] for c in cases) / len(cases), 2),
        "by_format": {},
    }
    for fmt in sorted({c["format"] for c in scored}):
        cs = [c for c in scored if c["format"] == fmt]
        tot = sum(len(c["fields_ok"]) for c in cs)
        summary["by_format"][fmt] = round(sum(sum(c["fields_ok"].values()) for c in cs) / tot, 3)
    run = EvalRun(model=model, summary=summary, cases=cases)
    db.add(run)
    db.commit()
    out = EVAL_DIR / "results"
    out.mkdir(exist_ok=True)
    (out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{model}.json").write_text(
        json.dumps({"summary": summary, "cases": cases}, indent=2)
    )
    return run


def main() -> None:
    from ..db import SessionLocal
    from ..seed import ensure_schema_and_seed

    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--provider")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    ensure_schema_and_seed()
    db = SessionLocal()
    run = run_evals(db, a.model, a.provider, a.only)
    print(json.dumps(run.summary, indent=2))


if __name__ == "__main__":
    main()
