"""Create Document + Claim rows from an uploaded file or an email (deduplicated by content hash / message id)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import Claim, Document
from .queue import enqueue

MAX_BYTES = 25 * 1024 * 1024


def new_reference() -> str:
    return f"FNOL-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(3).upper()}"


def ingest_bytes(
    db: Session,
    data: bytes,
    filename: str,
    content_type: str,
    *,
    source: str = "upload",
    actor: str = "system",
    email_message_id: str | None = None,
    email_subject: str | None = None,
    email_from: str | None = None,
) -> tuple[Document, Claim, bool]:
    if len(data) > MAX_BYTES:
        raise ValueError(f"{filename} is larger than 25 MB")
    if not data:
        raise ValueError(f"{filename} is empty")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == sha))
    if existing is None and email_message_id:
        existing = db.scalar(select(Document).where(Document.email_message_id == email_message_id))
    if existing is not None:
        claim = existing.claims[0]
        audit.record(
            db,
            "duplicate_ignored",
            claim_id=claim.id,
            document_id=existing.id,
            actor=actor,
            details={"filename": filename, "source": source, "sha256": sha},
        )
        return existing, claim, False

    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in Path(filename).name)[-120:] or "upload"
    path = get_settings().storage_dir / f"{sha[:16]}_{safe}"
    path.write_bytes(data)
    doc = Document(
        sha256=sha,
        filename=filename,
        content_type=content_type or "application/octet-stream",
        storage_path=str(path),
        size_bytes=len(data),
        source=source,
        email_message_id=email_message_id,
        email_subject=email_subject,
        email_from=email_from,
    )
    db.add(doc)
    db.flush()
    claim = Claim(reference=new_reference(), document_id=doc.id, status="queued")
    db.add(claim)
    db.flush()
    audit.record(
        db,
        "received",
        claim_id=claim.id,
        document_id=doc.id,
        actor=actor,
        details={
            "filename": filename,
            "source": source,
            "bytes": len(data),
            "sha256": sha,
            "email_subject": email_subject,
        },
    )
    enqueue(db, "process_claim", {"claim_id": claim.id}, dedupe_key=f"process:{claim.id}:0")
    return doc, claim, True
