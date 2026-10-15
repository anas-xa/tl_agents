"""Compliance agent for licence-linked requirements (E3-S3).

* ``RequirementRule``  versioned requirement catalogue (confirmed: licence expiry, valid Ejari, Dubai Chambers
                       membership; everything else is a typed 'to be confirmed by DET' rule, outside totals).
* ``SourceValue``      a value with its source label and history (owner-entered value kept when a source replaces it).
* ``ConflictLog``      'Sources differ' / 'Source differs from your entry' records.
* ``Evaluation``       the daily evaluation result per requirement.
* ``ComplianceDraft``  documents prepared in advance (renewal checklist pack): AI-prepared, bilingual, review status.
* ``ReviewRecord``     K15 review record classified against material_fields_v1.
* ``ApprovalRecord``   approval-registry record (internal status change only; nothing is sent to DET or Ejari).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

REQUIREMENT_TYPES = ("licence_expiry", "ejari_expiry", "chambers_membership", "other")
STATUSES = ("met", "due_soon", "at_risk", "overdue", "unknown", "to_be_confirmed")
STATUS_PRECEDENCE = ("overdue", "at_risk", "due_soon", "met")
EVIDENCE = ("verified", "owner_declared", "unconfirmed", "not_applicable")
SOURCE_LABELS = ("DET", "Ejari", "owner-declared")
INTERNAL_STATUS = ("active", "expired_or_in_grace", "suspended", "cancelled", "unknown", "needs_review")
REVIEW_STATUSES = ("draft_not_reviewed", "reviewed", "returned_for_changes", "approved_by_owner", "discarded")
OUTPUT_TYPES = ("renewal_checklist", "document_pack")
K15_OUTCOMES = ("accepted", "accepted_edited", "rejected")
K15_CLASSES = ("accepted_without_material_change", "accepted_with_material_change", "accepted_with_non_material_change")


class RequirementRule(Base):
    __tablename__ = "compliance_requirement_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("crr"))
    requirement_type: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(60), index=True)
    title_en: Mapped[str] = mapped_column(String(255))
    title_ar: Mapped[str] = mapped_column(String(255))
    activity_code: Mapped[str | None] = mapped_column(String(40))
    approving_authority: Mapped[str] = mapped_column(String(120))
    instrument: Mapped[str] = mapped_column(String(400))
    effective_date: Mapped[date | None] = mapped_column(Date)
    confirmation_status: Mapped[str] = mapped_column(String(30))  # confirmed | to_be_confirmed
    source_reference: Mapped[str | None] = mapped_column(String(400))
    last_confirmed: Mapped[date | None] = mapped_column(Date)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    due_soon_days: Mapped[int | None] = mapped_column(Integer)
    at_risk_days: Mapped[int | None] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceValue(Base):
    __tablename__ = "compliance_source_values"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("csv"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str | None] = mapped_column(String(40))
    requirement_type: Mapped[str] = mapped_column(String(40))
    value_date: Mapped[date | None] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(80))  # e.g. Ejari contract number
    source_label: Mapped[str] = mapped_column(String(30))  # SOURCE_LABELS
    match_basis: Mapped[str | None] = mapped_column(String(60))  # licence_number | ejari_contract+premises | premises_text (weak)
    declared_by_uuid: Mapped[str | None] = mapped_column(String(64))
    declared_by_role: Mapped[str | None] = mapped_column(String(40))
    evidence_ref: Mapped[str | None] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)  # kept in history when a source read replaces it
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ConflictLog(Base):
    __tablename__ = "compliance_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    requirement_type: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))  # sources_differ | source_differs_from_entry
    values: Mapped[list | None] = mapped_column(JSON)
    chosen: Mapped[str | None] = mapped_column(String(20))
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evaluation(Base):
    __tablename__ = "compliance_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    requirement_type: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[str] = mapped_column(String(20))
    due_date: Mapped[date | None] = mapped_column(Date)
    source_label: Mapped[str | None] = mapped_column(String(30))
    as_of_date: Mapped[datetime | None] = mapped_column(DateTime)
    gap_days: Mapped[int | None] = mapped_column(Integer)
    rule_version: Mapped[str | None] = mapped_column(String(20))
    threshold_version: Mapped[str | None] = mapped_column(String(20))
    match_basis: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[list | None] = mapped_column(JSON)
    evaluated_on: Mapped[date] = mapped_column(Date, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ComplianceDraft(Base):
    __tablename__ = "compliance_drafts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cdr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    output_type: Mapped[str] = mapped_column(String(40))  # OUTPUT_TYPES
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)  # {"en": {...}, "ar": {...}, "fields": {...}}
    original_content: Mapped[dict] = mapped_column(JSON)
    ai_prepared: Mapped[bool] = mapped_column(Boolean, default=True)  # permanent tag
    review_status: Mapped[str] = mapped_column(String(30), default="draft_not_reviewed")
    reviewed_by_role: Mapped[str | None] = mapped_column(String(40))
    reviewed_by_name: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by_name: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    k28_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    k28_mismatched: Mapped[list | None] = mapped_column(JSON)
    released: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_role: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewRecord(Base):
    __tablename__ = "compliance_review_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("k15"))
    output_id: Mapped[str] = mapped_column(String(40), index=True)
    output_type: Mapped[str] = mapped_column(String(40))
    output_version_original: Mapped[int] = mapped_column(Integer)
    output_version_final: Mapped[int] = mapped_column(Integer)
    reviewer_key: Mapped[str | None] = mapped_column(String(64))
    reviewer_role: Mapped[str | None] = mapped_column(String(40))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str] = mapped_column(String(20))
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    classification: Mapped[str | None] = mapped_column(String(60))
    material_fields_version: Mapped[str] = mapped_column(String(30), default="material_fields_v1")


class ApprovalRecord(Base):
    __tablename__ = "compliance_approval_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("car"))
    draft_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    approver_key: Mapped[str] = mapped_column(String(64))
    approver_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40), default="approve_internal_status_only")
    data_version: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    external_write: Mapped[bool] = mapped_column(Boolean, default=False)  # always False in this increment
    note: Mapped[str | None] = mapped_column(Text)
