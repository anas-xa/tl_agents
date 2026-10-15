"""Audit agent data model (E7-S1 .. E7-S4).

Exception flags are neutral 'items for review' (never findings). The audit-required result is an indicator,
never a legal determination. The working file is an unsigned 'audit work draft'. Review acts by a licensed
auditor are recorded as 'Record review' (an internal record, not a signature) while signing is switched off.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

# --- E7-S1 ---------------------------------------------------------------------------------------
SEVERITIES = ("High", "Medium", "Low")  # pilot scale; info/review/urgent scale 'to be confirmed'
FLAG_STATUSES = ("New", "Confirmed", "Explained", "Dismissed", "Escalated")
HUMAN_REVIEW_STATUSES = ("pending", "confirmed", "explained", "dismissed")
DECISIONS = ("confirm", "explain", "dismiss")
DECISION_TO_STATUS = {"confirm": "Confirmed", "explain": "Explained", "dismiss": "Dismissed"}
SOURCES = ("ledger", "e_invoice", "bank")
LEGAL_ANCHORS = ("anchored", "heuristic")
CYCLE_STATUSES = ("completed", "cancelled_on_withdrawal", "refused_no_source", "failed")
RULE_RELEVANT_FIELDS = ("amount", "date", "counterparty", "account_code", "vat_code", "currency", "invoice_number")
MASKED_FIELDS = ("counterparty", "description", "amount", "account_code")

# --- E7-S2 ---------------------------------------------------------------------------------------
AUDIT_FLAG_STATES = ("likely_required", "likely_not_required", "cannot_determine", "not_yet_assessed")
REQUIRED_REASONS = ("revenue_threshold", "qualifying_free_zone_person", "tax_group", "other_trigger")
# Reason codes for 'cannot determine' (orchestrator brief) plus two detail codes from the spec.
CANNOT_DETERMINE_REASONS = ("missing_profile", "near_threshold", "source_conflict", "coverage_failure", "stale_data", "at_threshold", "non_standard_period")
REVENUE_SOURCES = ("ledger", "e_invoice", "owner_declared")
CONFIRMATION_STATES = ("indicative_pending_expert_confirmation", "confirmed")
CRITERIA_STATUSES = ("proposed", "confirmed", "published")
OWNER_ACTIONS = ("acknowledge", "hide_banner", "dispute", "request_review", "ask_auditor")
DISPUTE_CODES = ("revenue_wrong", "tax_group_wrong", "qfzp_wrong", "period_wrong", "other")
TAX_GROUP_VALUES = ("yes", "no", "dont_know")
QFZP_VALUES = ("yes", "no", "not_applicable", "unknown")
DECLARATION_STATES = ("fta_confirmed", "self_declared_unverified", "not_declared_unverified", "owner_entered_unverified")

# --- E7-S3 ---------------------------------------------------------------------------------------
FILE_STATUSES = ("draft", "under_review", "signed", "rejected")
FILE_TRANSITIONS = {("draft", "under_review"), ("under_review", "signed"), ("under_review", "rejected"), ("rejected", "draft")}
COMPLETENESS_STATES = ("incomplete", "complete", "complete_with_exceptions")
GAP_STATUSES = ("open", "requested", "received", "overdue")
GAP_ACTIONS = ("add_statements", "reconnect_bank", "ask_my_accountant")

# --- E7-S4 ---------------------------------------------------------------------------------------
ENGAGEMENT_STATUSES = ("not_assigned", "in_preparation", "awaiting_review", "under_review", "review_recorded", "returned_to_preparation", "rejected", "signed_outside_platform")
REJECTION_CODES = ("data_missing", "data_inconsistent", "outside_my_competence", "other")
REGISTER_STATUSES = ("active", "suspended", "expired", "struck_off", "unlisted")
REGISTER_OUTCOMES = ("allowed", "blocked_suspended", "blocked_expired", "blocked_struck_off", "blocked_unlisted", "blocked_ambiguous", "blocked_unreachable", "blocked_stale_snapshot", "blocked_no_signing_authority")


class ExceptionRule(Base):
    """Versioned exception rule register (AX01..AX08, AX01b, cash rule). A threshold change = new rule_version."""

    __tablename__ = "audit_exception_rules"
    __table_args__ = (UniqueConstraint("rule_id", "rule_version", name="uq_audit_rule_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(20), index=True)
    rule_version: Mapped[str] = mapped_column(String(10), default="r1")
    title_en: Mapped[str] = mapped_column(String(255))
    title_ar: Mapped[str] = mapped_column(String(255))
    effective_date: Mapped[date] = mapped_column(Date)
    change_reason: Mapped[str] = mapped_column(Text, default="first version")
    owner: Mapped[str] = mapped_column(String(120), default="Qeonix product owner")
    approved_by_tax_specialist: Mapped[str | None] = mapped_column(String(120))
    sources_read: Mapped[list] = mapped_column(JSON, default=list)
    fields_read: Mapped[list] = mapped_column(JSON, default=list)
    default_severity: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    bank_dependent: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_anchor: Mapped[str] = mapped_column(String(12), default="heuristic")
    instrument: Mapped[str | None] = mapped_column(String(255))
    phase: Mapped[str] = mapped_column(String(10), default="1A")  # 1A ledger rules | bank (after consent and route)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="provisional")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExceptionRuleOverride(Base):
    """Per-company tuning (the cash rule is explicitly per-company tunable)."""

    __tablename__ = "audit_exception_rule_overrides"
    __table_args__ = (UniqueConstraint("company_id", "rule_id", name="uq_audit_rule_override"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_id: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    parameters: Mapped[dict | None] = mapped_column(JSON)
    set_by: Mapped[str | None] = mapped_column(String(120))
    set_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewCycle(Base):
    """Evaluation record of one review cycle: source references, rule versions, model version, timestamp."""

    __tablename__ = "audit_review_cycles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cyc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    sources_read: Mapped[list] = mapped_column(JSON, default=list)
    sources_refused: Mapped[dict] = mapped_column(JSON, default=dict)  # source -> consent state
    source_refs: Mapped[list] = mapped_column(JSON, default=list)  # record references only
    rule_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(60))
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    batches_saved: Mapped[int] = mapped_column(Integer, default=0)
    batches_discarded: Mapped[int] = mapped_column(Integer, default=0)
    flags_created: Mapped[int] = mapped_column(Integer, default=0)
    revisions_created: Mapped[int] = mapped_column(Integer, default=0)
    unable_to_assess: Mapped[dict] = mapped_column(JSON, default=dict)
    more_available: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(60))


class ExceptionFlag(Base):
    """Flag lineage. Lineage key = company, rule_id, period, anchor records. rule_id/rule_version copied at flag time."""

    __tablename__ = "audit_exception_flags"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("flag"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_id: Mapped[str] = mapped_column(String(20), index=True)
    rule_version: Mapped[str] = mapped_column(String(10))  # at flag time, never updated
    period: Mapped[str] = mapped_column(String(40))
    anchor_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(12), default="ledger")
    current_revision_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(12), default="New")  # FLAG_STATUSES
    human_review_status: Mapped[str] = mapped_column(String(12), default="pending")
    severity: Mapped[str] = mapped_column(String(10))
    flagged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    evidence_changed_since: Mapped[datetime | None] = mapped_column(DateTime)  # banner until a new decision
    source_withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    based_on_data_up_to: Mapped[date | None] = mapped_column(Date)
    escalation_case_id: Mapped[str | None] = mapped_column(String(40))
    audit_file_id: Mapped[str | None] = mapped_column(String(40), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class FlagRevision(Base):
    __tablename__ = "audit_flag_revisions"
    __table_args__ = (UniqueConstraint("flag_id", "revision_no", name="uq_flag_revision"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("frev"))
    flag_id: Mapped[str] = mapped_column(String(40), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(120), default="AI agent")
    change_summary: Mapped[str] = mapped_column(String(255))
    rule_id: Mapped[str] = mapped_column(String(20))
    rule_version: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))
    flag_type: Mapped[str] = mapped_column(String(60))
    reason_code: Mapped[str] = mapped_column(String(60))
    evidence_set: Mapped[list] = mapped_column(JSON, default=list)  # [{record_id, record_version}]
    evidence_rows: Mapped[list] = mapped_column(JSON, default=list)  # rule-relevant values as read
    basis: Mapped[dict | None] = mapped_column(JSON)  # rule parameters used (thresholds), shown to reviewers
    evidence_hash: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    superseded_before_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    masked: Mapped[bool] = mapped_column(Boolean, default=False)


class FlagDecision(Base):
    """Decision on one flag revision; changes are new entries (superseded_by links). Feeds K16."""

    __tablename__ = "audit_flag_decisions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fdec"))
    flag_id: Mapped[str] = mapped_column(String(40), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(10))  # DECISIONS
    reason: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    decided_by_uuid: Mapped[str | None] = mapped_column(String(64))
    decided_by_name: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(40))
    role_label: Mapped[str | None] = mapped_column(String(160))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decision_month: Mapped[str] = mapped_column(String(7))  # Asia/Dubai YYYY-MM
    rule_id: Mapped[str] = mapped_column(String(20))
    rule_version: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))
    superseded_by: Mapped[str | None] = mapped_column(String(40))
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    engagement_id: Mapped[str | None] = mapped_column(String(40))


class EvidenceMask(Base):
    __tablename__ = "audit_evidence_masks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flag_id: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(12))
    masked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deletion_due_at: Mapped[datetime] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


# --- E7-S2 audit-required indicator --------------------------------------------------------------------


class AuditCriteriaVersion(Base):
    """Versioned criteria rows (four-eyes: proposed by a tax specialist, confirmed by a different licensed audit expert)."""

    __tablename__ = "audit_criteria_versions"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # 'v1'
    instrument: Mapped[str] = mapped_column(String(255))
    effective_date: Mapped[date] = mapped_column(Date)
    effective_scope: Mapped[str] = mapped_column(String(255))
    triggers: Mapped[dict] = mapped_column(JSON)
    near_threshold_band_pct: Mapped[int] = mapped_column(Integer, default=10)
    projection_band_pct: Mapped[int] = mapped_column(Integer, default=20)
    revenue_source_tolerance_pct: Mapped[int] = mapped_column(Integer, default=5)
    short_period_mode: Mapped[str] = mapped_column(String(40), default="actual_not_prorated")
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    proposed_by: Mapped[str | None] = mapped_column(String(120))
    proposed_by_role: Mapped[str | None] = mapped_column(String(40))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    label: Mapped[str] = mapped_column(String(255), default="[REG] confirm before quoting")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditInputs(Base):
    """Declarations used by the indicator (tax group, QFZP, period). Never inferred."""

    __tablename__ = "audit_inputs"

    company_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_group_member: Mapped[str | None] = mapped_column(String(10))  # TAX_GROUP_VALUES
    tax_group_state: Mapped[str] = mapped_column(String(40), default="not_declared_unverified")
    qfzp: Mapped[str] = mapped_column(String(16), default="not_applicable")  # QFZP_VALUES
    qfzp_state: Mapped[str] = mapped_column(String(40), default="not_declared_unverified")
    declared_by: Mapped[str | None] = mapped_column(String(120))
    declared_by_role: Mapped[str | None] = mapped_column(String(40))
    declared_at: Mapped[datetime | None] = mapped_column(DateTime)
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditRevenueFigure(Base):
    """Revenue of the tax period per source (net of VAT, fils). A source counts only if it covers the full period."""

    __tablename__ = "audit_revenue_figures"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("arev"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20))  # REVENUE_SOURCES
    amount_fils: Mapped[int] = mapped_column(Integer)  # as stated
    vat_fils: Mapped[int] = mapped_column(Integer, default=0)  # stripped to get net of VAT
    covers_full_period: Mapped[bool] = mapped_column(Boolean, default=True)
    months_covered: Mapped[int | None] = mapped_column(Integer)
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    as_of: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    entered_by: Mapped[str | None] = mapped_column(String(120))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditRequiredResult(Base):
    __tablename__ = "audit_required_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("arr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_id: Mapped[str | None] = mapped_column(String(40))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_months: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(24))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    cannot_determine_reasons: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    caveats: Mapped[list] = mapped_column(JSON, default=list)
    criteria_version_id: Mapped[str] = mapped_column(String(20))
    instrument: Mapped[str] = mapped_column(String(255))
    confirmation_state: Mapped[str] = mapped_column(String(40))
    revenue_source: Mapped[str | None] = mapped_column(String(20))
    revenue_figures: Mapped[list] = mapped_column(JSON, default=list)
    governing_revenue_fils: Mapped[int | None] = mapped_column(Integer)
    twelve_month_equivalent_fils: Mapped[int | None] = mapped_column(Integer)
    near_threshold: Mapped[bool] = mapped_column(Boolean, default=False)
    input_version_hash: Mapped[str] = mapped_column(String(64))
    run_key: Mapped[str] = mapped_column(String(64), unique=True)
    case_id: Mapped[str | None] = mapped_column(String(40))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    previous_result: Mapped[str | None] = mapped_column(String(24))
    change_cause: Mapped[str | None] = mapped_column(String(40))
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    banner_hidden_at: Mapped[datetime | None] = mapped_column(DateTime)
    not_refreshed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditFlagAction(Base):
    """Owner actions on the indicator: acknowledge, hide banner, dispute data, request human review. Never an override."""

    __tablename__ = "audit_flag_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("afa"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    result_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    reason_text: Mapped[str | None] = mapped_column(Text)  # stored on the action, never in audit-trail details
    by_uuid: Mapped[str | None] = mapped_column(String(64))
    by_name: Mapped[str | None] = mapped_column(String(120))
    by_role: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    case_id: Mapped[str | None] = mapped_column(String(40))


class RecomputeJob(Base):
    """Recompute queue per company + period, coalesced; retries 1m/5m/30m/2h then dead letter."""

    __tablename__ = "audit_recompute_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("arj"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    cause: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | retrying | done | dead_letter
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


# --- E7-S3 draft audit working file ---------------------------------------------------------------------


class AuditWorkingFile(Base):
    """'Audit work draft' deliverable (type audit_file_draft, class B, signature required). One row per version."""

    __tablename__ = "audit_working_files"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("awf"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    deliverable_type: Mapped[str] = mapped_column(String(40), default="audit_file_draft")
    type_class: Mapped[str] = mapped_column(String(2), default="B")
    signature_required: Mapped[bool] = mapped_column(Boolean, default=True)
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(14), default="draft")  # FILE_STATUSES
    release_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    completeness_state: Mapped[str] = mapped_column(String(26), default="incomplete")
    check_version: Mapped[str] = mapped_column(String(10), default="ac-v1")
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    first_draft_created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    first_complete_draft_ready_at: Mapped[datetime | None] = mapped_column(DateTime)  # immutable once set (K18)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    out_of_date: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_on: Mapped[datetime | None] = mapped_column(DateTime)
    changed_by: Mapped[str | None] = mapped_column(String(120))
    ai_prepared_content: Mapped[dict] = mapped_column(JSON, default=dict)
    human_approved_content: Mapped[dict | None] = mapped_column(JSON)
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    signer_name: Mapped[str | None] = mapped_column(String(120))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
    document_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    engagement_id: Mapped[str | None] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(60), default="rules-v1")
    source_record_links: Mapped[list] = mapped_column(JSON, default=list)
    calculation_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    exception_ids: Mapped[list] = mapped_column(JSON, default=list)
    signature_void: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DataGap(Base):
    __tablename__ = "audit_data_gaps"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gap"))
    file_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    gap_number: Mapped[int] = mapped_column(Integer)
    check: Mapped[str] = mapped_column(String(4))  # ac-v1 check letter
    item_en: Mapped[str] = mapped_column(String(255))
    item_ar: Mapped[str] = mapped_column(String(255))
    why_en: Mapped[str] = mapped_column(String(255))
    why_ar: Mapped[str] = mapped_column(String(255))
    who_can_fix: Mapped[str] = mapped_column(String(30), default="owner")
    status: Mapped[str] = mapped_column(String(10), default="open")
    action: Mapped[str] = mapped_column(String(20), default="add_statements")
    assignee_uuid: Mapped[str | None] = mapped_column(String(64))
    assignee_name: Mapped[str | None] = mapped_column(String(120))
    due_date: Mapped[date | None] = mapped_column(Date)
    history: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(30), default="AI agent")
    provided_at: Mapped[datetime | None] = mapped_column(DateTime)
    reminders_sent: Mapped[list] = mapped_column(JSON, default=list)
    held_for_owner_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reassigned_note: Mapped[bool] = mapped_column(Boolean, default=False)


class FileStatusHistory(Base):
    __tablename__ = "audit_file_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(40), index=True)
    who: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    from_status: Mapped[str | None] = mapped_column(String(14))
    to_status: Mapped[str] = mapped_column(String(14))
    invalid: Mapped[bool] = mapped_column(Boolean, default=False)
    invalid_since: Mapped[datetime | None] = mapped_column(DateTime)
    invalid_reason: Mapped[str | None] = mapped_column(String(40))


# --- E7-S4 licensed-auditor review --------------------------------------------------------------------


class RegisterSnapshot(Base):
    """Dated snapshot of the Ministry of Economy auditor register (mock source; no API assumed)."""

    __tablename__ = "audit_register_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("snap"))
    loaded_by: Mapped[str] = mapped_column(String(120))
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(160), default="Ministry of Economy auditor register (mock)")
    entries: Mapped[list] = mapped_column(JSON, default=list)


class RegisterCheck(Base):
    __tablename__ = "audit_register_checks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rchk"))
    engagement_id: Mapped[str | None] = mapped_column(String(40), index=True)
    auditor_identity_uuid: Mapped[str] = mapped_column(String(64))
    register_ref: Mapped[str | None] = mapped_column(String(40))
    snapshot_id: Mapped[str | None] = mapped_column(String(40))
    snapshot_loaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    purpose: Mapped[str] = mapped_column(String(20), default="assignment")  # assignment | review | sign
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Engagement(Base):
    __tablename__ = "audit_engagements"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("eng"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    working_file_id: Mapped[str | None] = mapped_column(String(40))
    auditor_identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    auditor_name: Mapped[str] = mapped_column(String(120))
    register_ref: Mapped[str | None] = mapped_column(String(40))
    firm_name: Mapped[str | None] = mapped_column(String(160))
    engagement_manager: Mapped[str] = mapped_column(String(160))  # firm contact, fallback DET pilot manager queue
    engagement_manager_is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    preparing_team: Mapped[str] = mapped_column(String(60), default="qeonix_audit_ops")
    assigned_by: Mapped[str] = mapped_column(String(120))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reassignment_log: Mapped[list] = mapped_column(JSON, default=list)
    review_deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="awaiting_review")
    firewall_record_id: Mapped[str | None] = mapped_column(String(40))
    register_check_id: Mapped[str | None] = mapped_column(String(40))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reminders_sent: Mapped[list] = mapped_column(JSON, default=list)
    escalations_sent: Mapped[list] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ReauthAssertion(Base):
    """UAE PASS re-authentication assertion reference (mock step-up). Review acts need one no older than 5 minutes."""

    __tablename__ = "audit_reauth_assertions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("reauth"))
    identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(40), default="uae_pass_step_up_mock")
    used_for: Mapped[str | None] = mapped_column(String(40))


class AuditorReviewRecord(Base):
    """'Record review' (Phase 1): internal record, not a signature."""

    __tablename__ = "audit_review_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("revrec"))
    engagement_id: Mapped[str] = mapped_column(String(40), index=True)
    file_id: Mapped[str] = mapped_column(String(40))
    file_version_no: Mapped[int] = mapped_column(Integer)
    version_hash: Mapped[str] = mapped_column(String(64))
    reviewer_identity_uuid: Mapped[str] = mapped_column(String(64))
    reviewer_name: Mapped[str] = mapped_column(String(120))
    register_no: Mapped[str | None] = mapped_column(String(40))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reauth_ref: Mapped[str] = mapped_column(String(40))
    snapshot_id: Mapped[str | None] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80), default="internal record, not a signature")
    supplied_documents_only: Mapped[bool] = mapped_column(Boolean, default=False)
    void: Mapped[bool] = mapped_column(Boolean, default=False)


class ReturnRecord(Base):
    """Return to preparation / rejection with a coded reason; free text released to the owner only at the auditor's choice."""

    __tablename__ = "audit_return_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ret"))
    engagement_id: Mapped[str] = mapped_column(String(40), index=True)
    file_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # request_changes | reject
    reason_code: Mapped[str] = mapped_column(String(30))
    free_text: Mapped[str | None] = mapped_column(Text)
    release_free_text: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_language: Mapped[str] = mapped_column(String(5), default="en")
    by_uuid: Mapped[str] = mapped_column(String(64))
    by_name: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SignedOutsideRecord(Base):
    __tablename__ = "audit_signed_outside_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sop"))
    engagement_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reporter_name: Mapped[str] = mapped_column(String(120))
    reporter_role: Mapped[str] = mapped_column(String(40))
    signer_name: Mapped[str] = mapped_column(String(120))
    register_number: Mapped[str] = mapped_column(String(40))
    date_signed: Mapped[date] = mapped_column(Date)
    document_reference: Mapped[str] = mapped_column(String(80))
    file_version_no: Mapped[int] = mapped_column(Integer)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class SignRecord(Base):
    """Sign record, built but unreachable while audit.signing.enabled is false."""

    __tablename__ = "audit_sign_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sign"))
    engagement_id: Mapped[str] = mapped_column(String(40), index=True)
    file_id: Mapped[str] = mapped_column(String(40))
    signer_identity_uuid: Mapped[str] = mapped_column(String(64))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    firm: Mapped[str | None] = mapped_column(String(160))
    version_hash: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(20), default="sig-v1")
    signing_method: Mapped[str] = mapped_column(String(60), default="uae_pass_assertion_as_approval")
    register_snapshot_id: Mapped[str | None] = mapped_column(String(40))
    reauth_ref: Mapped[str] = mapped_column(String(40))
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
