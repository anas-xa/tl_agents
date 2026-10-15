"""Immutable audit trail (E1-S3).

* Append-only ``audit_events`` with a hash chain (``prev_hash`` -> ``hash``) so tampering is detectable.
* Actor identity is stored as a pseudonymous ``actor_key``; the mapping to the real identity UUID lives
  in a separate ``actor_identity_map`` table with its own access rule.
* Corrections are appended as new events referencing the original (``corrects_event_id``), never edited.
* Writes that fail reach the ``audit_pending`` store so the caller can fail closed (sign-in) or retry.
* Exports need a reason code, a second approver and are themselves logged (``audit_exports``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.time import utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)  # e.g. SIGN_IN, CONSENT_GRANTED
    category: Mapped[str] = mapped_column(String(40), index=True)  # sign_in | access | agent | consent | approval | escalation | sign_off | config | data_access | billing | document | reminder | system
    outcome: Mapped[str] = mapped_column(String(20), default="success")  # success | refused | failed | info
    reason_code: Mapped[str | None] = mapped_column(String(60), index=True)
    actor_key: Mapped[str | None] = mapped_column(String(64), index=True)  # pseudonymous
    actor_role: Mapped[str | None] = mapped_column(String(60))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    licence_number: Mapped[str | None] = mapped_column(String(40), index=True)
    subject_type: Mapped[str | None] = mapped_column(String(60))  # entity type touched
    subject_id: Mapped[str | None] = mapped_column(String(80), index=True)
    details: Mapped[dict | None] = mapped_column(JSON)  # never contains raw financial figures for sign-in events
    language: Mapped[str | None] = mapped_column(String(5))
    config_version: Mapped[str | None] = mapped_column(String(40))
    ip_truncated: Mapped[str | None] = mapped_column(String(50))  # IPv4 /24 or IPv6 /48
    browser_family: Mapped[str | None] = mapped_column(String(40))
    log_class: Mapped[str] = mapped_column(String(40), default="standard")  # retention class
    corrects_event_id: Mapped[str | None] = mapped_column(String(40))
    # Chain position, assigned when the writing transaction commits (see audit.service: sealing). The chain is
    # verified in seq order, so concurrent requests can never fork it.
    seq: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), default="")


class AuditChainHead(Base):
    """Single row holding the last sealed position; locked while a transaction seals its events."""

    __tablename__ = "audit_chain_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    last_hash: Mapped[str | None] = mapped_column(String(64))


class ActorIdentityMap(Base):
    """Separate identity mapping store: pseudonymous actor key -> identity UUID."""

    __tablename__ = "actor_identity_map"

    actor_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditPending(Base):
    """Pending store for events whose primary write failed."""

    __tablename__ = "audit_pending"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    replayed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditExport(Base):
    __tablename__ = "audit_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    export_id: Mapped[str] = mapped_column(String(40), unique=True)
    requested_by_key: Mapped[str] = mapped_column(String(64))
    approved_by_key: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(40))
    pseudonymised: Mapped[bool] = mapped_column(Boolean, default=True)
    filters: Mapped[dict | None] = mapped_column(JSON)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RetentionClass(Base):
    """Retention per log class, with a recorded legal basis (versioned via config as well)."""

    __tablename__ = "audit_retention_classes"

    log_class: Mapped[str] = mapped_column(String(40), primary_key=True)
    retention_months: Mapped[int | None] = mapped_column(Integer)  # None = empty until confirmed
    pseudonymise_after_months: Mapped[int | None] = mapped_column(Integer)
    legal_basis: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="to_be_confirmed")
    label: Mapped[str | None] = mapped_column(String(255))
