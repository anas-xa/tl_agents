"""Approval workflow and controlled submission (E6). Every record class here is append-only: corrections are
new rows or status events, nothing is overwritten or deleted. Approval is a permission inside this platform;
it is never a signature, a filing declaration or a power of attorney."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

SUBMISSION_TYPES = ("return_pack",)  # schema allows later types; only return_pack is enabled (config)
RETURN_TYPES = ("vat", "ct")
REQUEST_STATUSES = ("open", "decided", "superseded", "expired", "blocked", "in_preparation")
DECISIONS = ("approve", "reject", "request_changes")
APPROVAL_STATUSES = ("active", "pending_joint", "superseded", "expired", "withdrawn", "suspended", "declined")
CAPACITIES = ("owner", "partner", "manager", "signatory", "attorney")
APPROVER_CAPACITIES = ("owner", "authorised_signatory", "fta_recognised_agent", "delegate")
RULE_TYPES = ("any_one", "two_together", "unclear")
VERIFICATION_STATUSES = ("verified", "needs_reverification")
ACTIONS_APPROVED = ("submit_this_return_for_this_period", "release_for_manual_filing")
GRANT_STATUSES = ("active", "suspended", "expired", "revoked")
SCOPE_OPTIONS = ("single_return", "time_period")
# Live Phase 1 filing states; 'Sending', 'Sent', 'Unconfirmed', 'Filed (confirmed)' exist only as Demo data fixtures.
FILING_STATES = ("not_filed", "filed_outside_self_declared", "filed_outside_values_differ", "authority_unavailable", "blocked")
BLOCKED_CAUSES = ("approval_missing", "approval_expired", "data_changed_since_approval", "approver_no_longer_has_rights")
ATTEMPT_STATUSES = ("sending", "sent", "unconfirmed", "filed", "rejected", "escalated")
EXCEPTION_REASONS = ("no_valid_approval_found", "wrong_version", "approval_after_submission", "expired", "withdrawn", "approver_not_entitled", "record_incomplete")


class AuthorityHolder(Base):
    """Authority-evidence model (Q110): who may approve for a company, on which source document, until when,
    under which rule type. Configurable check, never a hard-coded legal test; every determination is logged."""

    __tablename__ = "approval_authority_holders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ah"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)  # bound once the UAE PASS identity matches
    display_name: Mapped[str] = mapped_column(String(255))
    capacity: Mapped[str] = mapped_column(String(20), default="owner")  # CAPACITIES
    source_document: Mapped[str] = mapped_column(String(160))  # DET record | attested POA / resolution | MOA signing clause
    source_version: Mapped[str | None] = mapped_column(String(40))
    action_class: Mapped[str] = mapped_column(String(40), default="approve_return")
    rule_type: Mapped[str] = mapped_column(String(20), default="unclear")  # RULE_TYPES
    quorum_n: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(String(30), default="verified")
    determination_note: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("apr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str] = mapped_column(String(40), index=True)  # return draft id (E5-S3 draft pack)
    submission_type: Mapped[str] = mapped_column(String(30), default="return_pack")
    return_type: Mapped[str] = mapped_column(String(5))
    period_id: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_date_source: Mapped[str | None] = mapped_column(String(40))
    amounts: Mapped[list | None] = mapped_column(JSON)  # [{key, value_fils}] figures shown on the request
    rule_version: Mapped[str | None] = mapped_column(String(120))
    human_review_status: Mapped[str | None] = mapped_column(String(50))
    draft_content_hash: Mapped[str] = mapped_column(String(64))
    pack_version: Mapped[int] = mapped_column(Integer, default=1)
    authority_rule_type: Mapped[str] = mapped_column(String(20), default="any_one")
    quorum_n: Mapped[int] = mapped_column(Integer, default=1)
    entitled_approvers: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="open")  # REQUEST_STATUSES
    status_reason: Mapped[str | None] = mapped_column(String(60))
    awaiting_owner: Mapped[bool] = mapped_column(Boolean, default=False)  # E6-S2 'awaiting owner approval'
    requested_by_uuid: Mapped[str | None] = mapped_column(String(64))
    requested_by_name: Mapped[str | None] = mapped_column(String(120))
    requested_by_role: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    link_expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    superseded_by: Mapped[str | None] = mapped_column(String(40))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime)
    uaepass_failures: Mapped[dict | None] = mapped_column(JSON)
    escalation_case_id: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(Base):
    """Append-only approval record (one per person per decision). Status moves only by appended events."""

    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("APV"))
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str] = mapped_column(String(40), index=True)
    submission_type: Mapped[str] = mapped_column(String(30), default="return_pack")
    decision: Mapped[str] = mapped_column(String(20))  # DECISIONS
    reason: Mapped[str | None] = mapped_column(Text)  # owner's own note (reject / request changes only)
    approver_uuid: Mapped[str] = mapped_column(String(64), index=True)
    approver_actor_key: Mapped[str | None] = mapped_column(String(80))
    approver_name: Mapped[str] = mapped_column(String(120))
    assurance_level: Mapped[str] = mapped_column(String(10))
    capacity: Mapped[str] = mapped_column(String(30))  # APPROVER_CAPACITIES
    display_role: Mapped[str] = mapped_column(String(40))  # Owner | Owner abroad | Delegate with owner's delegated right
    delegation_basis: Mapped[dict | None] = mapped_column(JSON)
    authority_evidence_ref: Mapped[str | None] = mapped_column(String(40))
    action_approved: Mapped[str] = mapped_column(String(40), default="release_for_manual_filing")
    data_version_hash: Mapped[str] = mapped_column(String(64))
    pack_version: Mapped[int] = mapped_column(Integer, default=1)
    rule_version_ids: Mapped[list | None] = mapped_column(JSON)
    ai_generated_label: Mapped[str | None] = mapped_column(String(160))
    human_review_status: Mapped[str | None] = mapped_column(String(50))
    informed_unreviewed_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_wording_version_id: Mapped[str] = mapped_column(String(40))
    declaration_wording: Mapped[dict | None] = mapped_column(JSON)  # exact EN + AR wording shown
    channel: Mapped[str] = mapped_column(String(40), default="web/UAE PASS click-to-approve")
    session_ref: Mapped[str | None] = mapped_column(String(40))
    device_family: Mapped[str | None] = mapped_column(String(20))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    capped_at_due_date: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # APPROVAL_STATUSES
    status_reason: Mapped[str | None] = mapped_column(String(60))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ApprovalStatusEvent(Base):
    """Supersession / expiry / withdrawal / suspension events. Earlier states are never deleted."""

    __tablename__ = "approval_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    approval_id: Mapped[str | None] = mapped_column(String(40), index=True)
    request_id: Mapped[str | None] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DelegateApprovalGrant(Base):
    """E6-S2 grant evidence record. No production effect while the per-company Phase B switch is OFF."""

    __tablename__ = "delegate_approval_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("GRT"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    delegate_uuid: Mapped[str] = mapped_column(String(64), index=True)
    delegate_name: Mapped[str | None] = mapped_column(String(120))
    granting_owner_uuid: Mapped[str] = mapped_column(String(64))
    granting_owner_name: Mapped[str | None] = mapped_column(String(120))
    granting_authority_ref: Mapped[str | None] = mapped_column(String(40))  # AuthorityHolder id
    authority_basis: Mapped[str | None] = mapped_column(String(160))
    right: Mapped[str] = mapped_column(String(40), default="approve_submissions")
    scope_option: Mapped[str] = mapped_column(String(20), default="single_return")
    scope_items: Mapped[list] = mapped_column(JSON, default=list)  # [{submission_type, tax_type, period_id}]
    max_amount_fils: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    status_reason: Mapped[str | None] = mapped_column(String(60))
    confirmation_wording_version: Mapped[str] = mapped_column(String(40))
    step_up_proof: Mapped[dict | None] = mapped_column(JSON)  # assurance level, session ref, time
    used_by_approval_id: Mapped[str | None] = mapped_column(String(40))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_by_uuid: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class GrantEvent(Base):
    __tablename__ = "delegate_approval_grant_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grant_id: Mapped[str] = mapped_column(String(40), index=True)
    event: Mapped[str] = mapped_column(String(40))  # grant_created | grant_revoked | grant_expired | grant_suspended | grant_reminder_14_days ...
    actor_uuid: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GateDecision(Base):
    """Pre-submission gate outcome for every send or release path; counted toward K23 monitoring."""

    __tablename__ = "approval_gate_decisions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gate"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str | None] = mapped_column(String(40), index=True)
    data_version_hash: Mapped[str | None] = mapped_column(String(64))
    approval_id: Mapped[str | None] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(String(30))  # adapter_send | manual_release | manual_filing_record
    caller_type: Mapped[str] = mapped_column(String(20), default="user")  # user | agent | job | api | admin
    caller_key: Mapped[str | None] = mapped_column(String(80))
    switch_state: Mapped[str | None] = mapped_column(String(10))
    outcome: Mapped[str] = mapped_column(String(10))  # pass | block
    reason_code: Mapped[str | None] = mapped_column(String(60))
    tax_type: Mapped[str | None] = mapped_column(String(5))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ManualFilingRecord(Base):
    """Owner-entered filing evidence (live Phase 1). Self-declared; never verified by the authority here."""

    __tablename__ = "approval_manual_filings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("MFR"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str] = mapped_column(String(40), index=True)
    request_id: Mapped[str | None] = mapped_column(String(40))
    approval_id: Mapped[str | None] = mapped_column(String(40), index=True)
    data_version_hash: Mapped[str | None] = mapped_column(String(64))
    tax_type: Mapped[str | None] = mapped_column(String(5))
    state: Mapped[str] = mapped_column(String(40))  # FILING_STATES
    filed_date: Mapped[date | None] = mapped_column(Date)
    authority_reference: Mapped[str | None] = mapped_column(String(80))
    figures_as_filed: Mapped[dict | None] = mapped_column(JSON)
    differences: Mapped[list | None] = mapped_column(JSON)
    receipt_meta: Mapped[dict | None] = mapped_column(JSON)  # 'Attached by you, not verified' (demo only)
    self_filed_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_by_uuid: Mapped[str | None] = mapped_column(String(64))
    recorded_by_name: Mapped[str | None] = mapped_column(String(120))
    recorded_by_role: Mapped[str | None] = mapped_column(String(30))
    acting_under_grant: Mapped[dict | None] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    edited_by_name: Mapped[str | None] = mapped_column(String(120))
    verification: Mapped[str] = mapped_column(String(30), default="self_reported")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ManualFilingEdit(Base):
    __tablename__ = "approval_manual_filing_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(40), index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    edited_by_uuid: Mapped[str | None] = mapped_column(String(64))
    edited_by_name: Mapped[str | None] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SubmissionAttempt(Base):
    """Adapter attempt (switched off in Phase 1; created only by the stub when every condition holds, or as a
    'Demo data' fixture)."""

    __tablename__ = "approval_submission_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("att"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str] = mapped_column(String(40))
    approval_id: Mapped[str] = mapped_column(String(40))
    data_version_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    tax_type: Mapped[str | None] = mapped_column(String(5))
    period_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="sending")
    send_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_back_results: Mapped[list | None] = mapped_column(JSON)
    authority_reference: Mapped[str | None] = mapped_column(String(80))
    status_map_version: Mapped[str | None] = mapped_column(String(20))
    escalation_case_id: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceException(Base):
    """E6-S4 exception case. Reviewers add notes and review status only; underlying records never change."""

    __tablename__ = "approval_compliance_exceptions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("EXC"))
    submission_ref: Mapped[str] = mapped_column(String(40), index=True)
    submission_kind: Mapped[str] = mapped_column(String(20))  # manual_filing | attempt
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    approval_id: Mapped[str | None] = mapped_column(String(40))
    reason_code: Mapped[str] = mapped_column(String(40))  # EXCEPTION_REASONS
    severity: Mapped[int] = mapped_column(Integer)
    case_owner_role: Mapped[str] = mapped_column(String(40))
    recipients: Mapped[list | None] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(20), default="open")  # open | acknowledged | contained | resolved
    reviewer_notes: Mapped[list | None] = mapped_column(JSON)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    root_cause: Mapped[dict | None] = mapped_column(JSON)  # {role: {text_ref, by, at}} DET pilot manager + Qeonix product owner
    corrective_action: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceAlert(Base):
    """Alert with IDs and codes only (no tax or bank data): in-portal queue + minimal role-mailbox email."""

    __tablename__ = "approval_compliance_alerts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("alr"))
    exception_id: Mapped[str] = mapped_column(String(40), index=True)
    alert_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[int] = mapped_column(Integer)
    recipient_role: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # case_owner | backup | notified
    channels: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)


class ComplianceJobRun(Base):
    __tablename__ = "approval_compliance_job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(20))  # daily_k23 | weekly_k24
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[dict | None] = mapped_column(JSON)
