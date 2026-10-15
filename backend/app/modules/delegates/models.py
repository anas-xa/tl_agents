"""Delegation registry, quarantine, per-case access grants, company hold state and auditor firewall records.

* Delegate invitations match on the salted Emirates ID hash only (``identity.service.hash_emirates_id``); the
  number itself is never stored. Email and mobile are delivery channels, never match keys.
* Rights live on ``companies.CompanyRole`` (``rights``/``functions``); this module keeps the invitation,
  the change history, quarantine decisions, grants, hold state and firewall records.
* In-app delegation is never described as a power of attorney.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

INVITATION_STATUSES = ("pending", "accepted", "expired", "withdrawn")
# SC11 function toggles (owner-facing names) -> CompanyRole.rights values.
TOGGLE_TO_RIGHT = {
    "view_dashboard": "view",
    "prepare_data": "prepare",
    "grant_bank_consent": "grant_consent",
    "approve_submissions": "approve_submissions",
    "change_subscription": "change_subscription",
}
RIGHT_TO_TOGGLE = {v: k for k, v in TOGGLE_TO_RIGHT.items()}
PHASE_A_TOGGLES = ("view_dashboard", "prepare_data")
PHASE_B_TOGGLES = ("grant_bank_consent", "approve_submissions", "change_subscription")
REMOVAL_REASONS = ("owner_removed", "identity_failed", "no_owner", "system")
QUARANTINE_STATUSES = ("quarantined", "released", "rejected", "reassigned")
TOUCHED_ACTIONS = ("created", "edited", "submitted")
HOLD_STATES = ("none", "signatory_change_hold", "no_owner")
FIREWALL_RESULTS = ("conflict_found", "no_conflict_found_in_det_records")  # never 'independent'
CHANGE_TYPES = (
    "invited", "resent", "withdrawn", "accepted", "expired", "rights_changed", "removed", "suspended", "reinstated",
    "quarantine_decision", "dormancy_flagged", "authority_suspended", "authority_restored",
)


class DelegateInvitation(Base):
    __tablename__ = "delegate_invitations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inv"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    emirates_id_hash: Mapped[str] = mapped_column(String(64), index=True)  # sole match key (salted hash)
    entered_name: Mapped[str | None] = mapped_column(String(255))  # soft check only, never a match key
    email: Mapped[str | None] = mapped_column(String(255))  # delivery only
    mobile: Mapped[str | None] = mapped_column(String(40))  # delivery only
    functions: Mapped[list | None] = mapped_column(JSON)
    rights: Mapped[list | None] = mapped_column(JSON)  # CompanyRole.rights values chosen by the owner
    token: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # INVITATION_STATUSES
    invited_by_uuid: Mapped[str] = mapped_column(String(64))
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    resent_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)  # set on activation
    company_role_id: Mapped[str | None] = mapped_column(String(40))
    name_differs: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DelegateChange(Base):
    """Change history (who, what, when) and the owner's 'Recent access changes' list."""

    __tablename__ = "delegate_changes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dch"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    change_type: Mapped[str] = mapped_column(String(40))  # CHANGE_TYPES
    delegate_identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)
    delegate_label: Mapped[str | None] = mapped_column(String(255))  # display name / entered name (never an identity number)
    subject_ref: Mapped[str | None] = mapped_column(String(40))  # role id / invitation id / quarantine id
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(80))
    changed_by_uuid: Mapped[str | None] = mapped_column(String(64))
    changed_by_role: Mapped[str | None] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)  # delegate saw the banner / access-ended screen


class QuarantinedDraft(Base):
    """Draft touched (created/edited/submitted) by a delegate whose rights were removed. Unusable until the owner decides."""

    __tablename__ = "quarantined_drafts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("qd"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    draft_type: Mapped[str] = mapped_column(String(60))  # e.g. bookkeeping_period, tax_return_draft
    draft_ref: Mapped[str] = mapped_column(String(80), index=True)
    delegate_identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    touched_action: Mapped[str] = mapped_column(String(20), default="edited")  # TOUCHED_ACTIONS
    marker: Mapped[str] = mapped_column(String(80), default="initiated by a removed delegate")
    status: Mapped[str] = mapped_column(String(20), default="quarantined")  # QUARANTINE_STATUSES
    data_version: Mapped[str | None] = mapped_column(String(80))
    quarantined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by_uuid: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_identity_level: Mapped[str | None] = mapped_column(String(10))
    reassigned_to_uuid: Mapped[str | None] = mapped_column(String(64))
    new_draft_ref: Mapped[str | None] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AccessGrant(Base):
    """Per-case access grant for a specialist or licensed auditor (E1-S2, Q264). Fail-closed without it."""

    __tablename__ = "access_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("grant"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    case_ref: Mapped[str] = mapped_column(String(80), index=True)  # case_id or engagement_id
    recipient_identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    recipient_role: Mapped[str] = mapped_column(String(40))  # specialist | licensed_auditor
    purpose: Mapped[str] = mapped_column(String(80))  # coded purpose, no free text
    data_scope: Mapped[list | None] = mapped_column(JSON)  # coded data types
    granted_by_uuid: Mapped[str] = mapped_column(String(64))
    granted_by_capacity: Mapped[str] = mapped_column(String(40), default="owner")
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_by_uuid: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class CompanyHold(Base):
    """Owner-change hold (settled Q12): none | signatory_change_hold | no_owner. Never released by timeout."""

    __tablename__ = "company_holds"

    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    hold_state: Mapped[str] = mapped_column(String(30), default="none")  # HOLD_STATES
    hold_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(String(80))
    alerted_det_operations_at: Mapped[datetime | None] = mapped_column(DateTime)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime)
    lifted_by: Mapped[str | None] = mapped_column(String(80))  # 'uaepass_match' | staff identity
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SupportQueueCase(Base):
    """DET onboarding support queue: signatory-change no-match cases (platform never edits DET data)."""

    __tablename__ = "det_support_queue"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sq"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    case_type: Mapped[str] = mapped_column(String(40), default="signatory_no_match")
    identity_uuid: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(80))


class FirewallRecord(Base):
    """Auditor firewall record per engagement; result wording never says 'independent'."""

    __tablename__ = "auditor_firewall_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fw"))
    engagement_id: Mapped[str] = mapped_column(String(80), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    auditor_identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    firm: Mapped[str | None] = mapped_column(String(255))
    related_entity_links_used: Mapped[list | None] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(40))  # FIREWALL_RESULTS
    independence_declared_at: Mapped[datetime | None] = mapped_column(DateTime)
    manual_conflict_flags: Mapped[list | None] = mapped_column(JSON)  # [{by_role, code, at}]
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | suspended
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    evaluation_count: Mapped[int] = mapped_column(Integer, default=1)
