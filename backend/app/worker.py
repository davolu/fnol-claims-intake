"""Background worker: processes queued claims, pushes approved claims, polls email connectors, runs evals.

Run with: python -m app.worker"""

from __future__ import annotations

import logging
import signal
import socket
import time
from datetime import UTC, datetime, timedelta

from . import audit
from .config import get_settings
from .db import SessionLocal
from .email_connectors.connectors import get_source, to_rfc2822
from .ingest import ingest_bytes
from .integrations.base import PushError
from .models import EmailConnector, Job
from .pipeline.emailparse import build_eml
from .pipeline.orchestrator import process_claim
from .pipeline.push import NotPushable, push_claim
from .queue import claim_next, enqueue, fail, finish

log = logging.getLogger("fnol.worker")
_running = True


def poll_connector(db, connector_id: str) -> dict:
    conn = db.get(EmailConnector, connector_id)
    if conn is None or not conn.is_active:
        return {"skipped": True}
    src = get_source(conn)
    new = 0
    seen = 0
    try:
        for em in src.fetch(max_results=int((conn.config or {}).get("max_results", 10))):
            seen += 1
            eml = build_eml(
                message_id=em.message_id or "",
                subject=em.subject,
                sender=em.sender,
                date=to_rfc2822(em.date),
                body=em.body,
                attachments=em.attachments,
            )
            _, _, created = ingest_bytes(
                db,
                eml,
                f"{(em.subject or 'email')[:60]}.eml",
                "message/rfc822",
                source=f"email:{conn.kind}",
                actor=f"connector:{conn.name}",
                email_message_id=em.message_id,
                email_subject=em.subject,
                email_from=em.sender,
            )
            new += int(created)
        conn.last_status = f"ok: {seen} matched, {new} new"
    except Exception as e:
        conn.last_status = f"error: {type(e).__name__}: {e}"[:500]
        raise
    finally:
        conn.last_polled_at = datetime.now(UTC)
        db.commit()
    audit.record(db, "email_polled", actor=f"connector:{conn.name}", details={"matched": seen, "new": new})
    db.commit()
    return {"matched": seen, "new": new}


def schedule_polls(db) -> None:
    s = get_settings()
    now = datetime.now(UTC)
    for conn in db.query(EmailConnector).filter(EmailConnector.is_active.is_(True)).all():
        last = conn.last_polled_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last is None or now - last >= timedelta(seconds=s.email_poll_seconds):
            bucket = int(now.timestamp() // s.email_poll_seconds)
            enqueue(db, "poll_email", {"connector_id": conn.id}, dedupe_key=f"poll:{conn.id}:{bucket}", max_attempts=1)
    db.commit()


def run_job(db, job: Job) -> None:
    p = job.payload or {}
    if job.kind == "process_claim":
        process_claim(db, p["claim_id"])
    elif job.kind == "push_claim":
        push_claim(db, p["claim_id"], actor=p.get("actor", "system"))
    elif job.kind == "poll_email":
        poll_connector(db, p["connector_id"])
    elif job.kind == "run_evals":
        from .evals.runner import run_evals

        run_evals(db, model=p.get("model"))
    else:
        raise ValueError(f"unknown job kind {job.kind}")


def work_once() -> bool:
    db = SessionLocal()
    try:
        job = claim_next(db)
        if job is None:
            return False
        try:
            run_job(db, job)
            finish(db, job)
        except NotPushable as e:
            db.rollback()
            fail(db, db.get(Job, job.id) or job, str(e), retryable=False)
        except ValueError as e:  # bad input (unsupported file etc.): retrying will not help
            db.rollback()
            fail(db, db.get(Job, job.id) or job, str(e), retryable=False)
        except PushError as e:
            db.rollback()
            fail(db, db.get(Job, job.id) or job, str(e), retryable=e.retryable)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            db.rollback()
            # processing failures of the LLM/network kind are retried with backoff
            fail(db, db.get(Job, job.id) or job, f"{type(e).__name__}: {e}", retryable=job.kind != "poll_email")
        return True
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    log.info("worker %s started", socket.gethostname())

    def _stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_sched = 0.0
    while _running:
        if time.time() - last_sched > 15:
            db = SessionLocal()
            try:
                schedule_polls(db)
            finally:
                db.close()
            last_sched = time.time()
        if not work_once():
            time.sleep(s.worker_poll_seconds)


if __name__ == "__main__":
    main()
