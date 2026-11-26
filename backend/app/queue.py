"""A small, durable job queue on the main database (no Redis needed).

Postgres: SELECT ... FOR UPDATE SKIP LOCKED lets several workers run safely.
SQLite (local/tests): single worker, plain UPDATE."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import is_postgres
from .models import Job


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
    delay_s: float = 0,
    max_attempts: int = 4,
) -> Job | None:
    if dedupe_key:
        existing = db.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        if existing:
            return None
    job = Job(
        kind=kind,
        payload=payload,
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
        run_after=datetime.now(UTC) + timedelta(seconds=delay_s),
    )
    try:
        with db.begin_nested():
            db.add(job)
    except IntegrityError:
        return None
    return job


def claim_next(db: Session) -> Job | None:
    now = datetime.now(UTC)
    q = select(Job).where(Job.status == "queued", Job.run_after <= now).order_by(Job.id).limit(1)
    if is_postgres():
        q = q.with_for_update(skip_locked=True)
    job = db.scalar(q)
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    db.commit()
    return job


def finish(db: Session, job: Job) -> None:
    job.status = "done"
    job.last_error = None
    db.commit()


def fail(db: Session, job: Job, error: str, retryable: bool = True) -> None:
    job.last_error = error[:2000]
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2**job.attempts))
    else:
        job.status = "failed"
    db.commit()
