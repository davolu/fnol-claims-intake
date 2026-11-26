"""Audit trail + step tracing. Every pipeline step and every human action lands here (PII-masked)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditEvent
from .security import mask_obj


def record(
    db: Session,
    event_type: str,
    *,
    claim_id: str | None = None,
    document_id: str | None = None,
    actor: str = "system",
    step: str | None = None,
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        claim_id=claim_id,
        document_id=document_id,
        actor=actor,
        event_type=event_type,
        step=step,
        details=mask_obj(details or {}),
        duration_ms=duration_ms,
    )
    db.add(ev)
    db.flush()
    return ev


class StepTimer:
    def __init__(self) -> None:
        self.details: dict[str, Any] = {}
        self.ms = 0


@contextmanager
def trace_step(
    db: Session,
    step: str,
    *,
    claim_id: str | None,
    document_id: str | None,
    timings: dict[str, int],
    actor: str = "agent",
) -> Iterator[StepTimer]:
    t = StepTimer()
    start = time.perf_counter()
    try:
        yield t
    except Exception as e:
        t.ms = int((time.perf_counter() - start) * 1000)
        record(
            db,
            "step_failed",
            claim_id=claim_id,
            document_id=document_id,
            actor=actor,
            step=step,
            details={**t.details, "error": f"{type(e).__name__}: {e}"},
            duration_ms=t.ms,
        )
        raise
    t.ms = int((time.perf_counter() - start) * 1000)
    timings[step] = timings.get(step, 0) + t.ms
    record(
        db,
        "step_completed",
        claim_id=claim_id,
        document_id=document_id,
        actor=actor,
        step=step,
        details=t.details,
        duration_ms=t.ms,
    )
