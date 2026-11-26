"""ORM models. JSON columns hold extraction results, validation output and traces."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(40), default="upload")  # upload | email:<connector>
    email_message_id: Mapped[str | None] = mapped_column(String(300), unique=True, nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_from: Mapped[str | None] = mapped_column(String(300), nullable=True)
    route: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    attachments: Mapped[list[Any]] = mapped_column(JSON, default=list)  # child attachment metadata for emails
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claims: Mapped[list[Claim]] = relationship(back_populates="document")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    # queued | processing | needs_review | approved | pushing | pushed | push_failed | rejected | failed
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation: Mapped[list[Any]] = mapped_column(JSON, default=list)
    review_reasons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)  # auto_push | review
    llm_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timings_ms: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Push to claims system (idempotent)
    push_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    push_attempts: Mapped[int] = mapped_column(Integer, default=0)
    external_system: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_claim_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_claim_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    push_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # step checkpoints for resumable push
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document: Mapped[Document] = relationship(back_populates="claims")
    events: Mapped[list[AuditEvent]] = relationship(back_populates="claim", order_by="AuditEvent.id")


class AuditEvent(Base):
    """Append-only audit trail. Details are PII-masked before they are written."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id"), index=True, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    step: Mapped[str | None] = mapped_column(String(60), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    claim: Mapped[Claim | None] = relationship(back_populates="events")


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30))  # guidewire | duckcreek | majesco | webhook
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    auth_mode: Mapped[str] = mapped_column(String(20), default="oauth2")  # oauth2 | basic | hmac | none
    token_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_stand_in: Mapped[bool] = mapped_column(Boolean, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailConnector(Base):
    __tablename__ = "email_connectors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30))  # composio_gmail | gmail_oauth | m365
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # non-secret settings
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Postgres-backed work queue (SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Policy(Base):
    """Local policy registry used by the policy-lookup tool (synced from the policy admin system)."""

    __tablename__ = "policies"

    policy_number: Mapped[str] = mapped_column(String(40), primary_key=True)
    insured_name: Mapped[str] = mapped_column(String(200))
    policy_type: Mapped[str] = mapped_column(String(40))  # PersonalAuto | Homeowners | CommercialProperty
    effective_date: Mapped[date] = mapped_column(Date)
    expiration_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="inforce")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    model: Mapped[str] = mapped_column(String(80))
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cases: Mapped[list[Any]] = mapped_column(JSON, default=list)
