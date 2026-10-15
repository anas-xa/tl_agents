"""Prompt-injection-safe document handling (E5-S4): documents with trust labels, isolation records,
adapter call log, guardrail test runs. Document text is never stored; only its hash and extracted fields."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

TRUST_LABELS = ("processing", "checked", "flagged")
FLAG_TYPES = ("A", "B", "C", "D", "E")
ESCALATION_STATUSES = ("sent", "being_checked", "checked", "returned_to_you")
PURPOSES = ("tax", "audit")


class GuardedDocument(Base):
    __tablename__ = "guard_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(255))
    uploader_uuid: Mapped[str | None] = mapped_column(String(64))
    uploader_name: Mapped[str | None] = mapped_column(String(120))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    file_type: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str] = mapped_column(String(10), default="tax")  # PURPOSES
    content_hash: Mapped[str] = mapped_column(String(64))
    trust_label: Mapped[str] = mapped_column(String(12), default="processing")  # TRUST_LABELS
    flag_type: Mapped[str | None] = mapped_column(String(1))
    flag_reason_key: Mapped[str | None] = mapped_column(String(20))  # catalogue key; never quotes document text
    internal_rule: Mapped[str | None] = mapped_column(String(80))  # reviewer view only
    screening_rule_version: Mapped[str | None] = mapped_column(String(20))
    extracted: Mapped[dict | None] = mapped_column(JSON)
    extracted_trust: Mapped[str] = mapped_column(String(12), default="unverified")  # unverified | checked
    missing_fields: Mapped[list | None] = mapped_column(JSON)
    escalation_id: Mapped[str | None] = mapped_column(String(40))
    escalation_status: Mapped[str | None] = mapped_column(String(20))
    escalation_route: Mapped[str | None] = mapped_column(String(40))
    expected_response_hours: Mapped[int | None] = mapped_column(Integer)
    review_open_by: Mapped[str | None] = mapped_column(String(64))  # one-at-a-time owner review lock
    cleared_by_uuid: Mapped[str | None] = mapped_column(String(64))
    cleared_by_name: Mapped[str | None] = mapped_column(String(120))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str | None] = mapped_column(String(20))  # cleared | rejected
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class IsolationRecord(Base):
    __tablename__ = "guard_isolation_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("iso"))
    document_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40))
    task_id: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    schema_keys: Mapped[list] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(60))
    output_matched_schema: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdapterCall(Base):
    """Every tool-adapter call, allowed or refused (agent, task, adapter, action; parameters as codes only)."""

    __tablename__ = "guard_adapter_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ac"))
    agent_id: Mapped[str] = mapped_column(String(60))
    task_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str | None] = mapped_column(String(40))
    adapter: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    policy_version: Mapped[str | None] = mapped_column(String(20))
    param_keys: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GuardrailRun(Base):
    __tablename__ = "guard_test_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gr"))
    suite_version: Mapped[str] = mapped_column(String(20))
    total: Mapped[int] = mapped_column(Integer)
    failed: Mapped[int] = mapped_column(Integer)
    failed_critical: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    release_blocked: Mapped[bool] = mapped_column(Boolean)
    report: Mapped[list | None] = mapped_column(JSON)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text)
