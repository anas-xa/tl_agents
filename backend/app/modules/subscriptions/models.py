"""Subscription, billing hook, payment allocation, opt-out/refund cases, complaints and first-run welcome
(E2-S2, E2-S3, E2-S4).

Invariants: the subscription is never a condition of licence issuance or renewal; its state never feeds back
into licence state; all money is integer fils; nothing is billed while billing_live is off or the fee
schedule is not confirmed; the owner's opt-out can never be disabled.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

SUBSCRIPTION_STATUSES = ("created", "pending_billing", "billing_requested", "pending_confirmation", "billed", "collected", "active", "held_for_review", "cancelled_by_opt_out", "opted_out", "cancelled", "paused", "ended")
# Enforced state machine (Q18 + AC/Q275). Any other transition is rejected and logged.
TRANSITIONS: dict[str, set[str]] = {
    "created": {"pending_billing"},
    "pending_billing": {"billing_requested", "held_for_review", "cancelled_by_opt_out", "ended"},
    "billing_requested": {"billed", "pending_confirmation", "held_for_review", "cancelled_by_opt_out"},
    "pending_confirmation": {"billed", "held_for_review"},
    "billed": {"collected", "active", "ended", "opted_out", "paused"},
    "collected": {"active", "ended"},
    "active": {"ended", "opted_out", "paused", "cancelled"},
    "paused": {"active", "ended"},
    "held_for_review": {"pending_billing", "ended"},  # by recorded human decision only
    "cancelled_by_opt_out": set(),
    "opted_out": set(),
    "cancelled": set(),
    "ended": set(),
}
ENROLMENT_BASES = ("default_on", "opted_in")
PENDING_BILLING_REASONS = ("fee_schedule_not_confirmed", "default_on_hold", "billing_live_off", "consent_required")
TERM_TYPES = ("whole_months", "part_term")
ALLOCATION_BASES = ("billing-line", "invoice-single-line", "platform-derived")
BILLING_STATUSES = ("requested", "pending_confirmation", "billed", "mismatch", "held", "cancelled")
COLLECTION_STATUSES = ("not_collected", "collected", "failed", "partially_collected", "refunded", "partially_refunded", "received_unallocated")
PAYMENT_TYPES = ("payment", "refund", "failure")
RECONCILIATION_TYPES = ("mismatch", "conflict", "aged_pending_confirmation", "billed_line_disappeared", "duplicate_lines", "missing_subscription", "unattributed_refund_excess", "overlap", "payment_channel_disagrees")
CASE_ACTIONS = ("opt_out", "refund", "complaint")
CASE_STATES = ("draft", "requested", "pending_DET", "applied", "rejected", "needs_DET_action", "cancelled")
CASE_TERMINAL = ("applied", "rejected", "cancelled")
DET_INSTRUCTION_STATES = ("not_sent", "sent", "pending_confirmation", "confirmed", "failed", "needs_DET_action")
COMPLAINT_STATUSES = ("received", "in_review", "replied", "resolved", "refunded", "rejected")


class Subscription(Base):
    """Key = licence_number + term_start_date. cohort_id, term_days, fee and enrolment_basis are immutable."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("licence_number", "start_date", name="uq_subscription_licence_term"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sub"))
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    licence_id: Mapped[str | None] = mapped_column(String(40))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    enrolment_basis: Mapped[str] = mapped_column(String(20))  # ENROLMENT_BASES, fixed at creation
    cohort_id: Mapped[str] = mapped_column(String(40))  # pilot cohort code + invoice month, e.g. PILOT1-2027-03
    cohort_register_id: Mapped[str | None] = mapped_column(String(40))
    cohort_version: Mapped[int | None] = mapped_column(Integer)
    wave: Mapped[str | None] = mapped_column(String(10))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)  # inclusive
    term_days: Mapped[int] = mapped_column(Integer)
    term_months: Mapped[int | None] = mapped_column(Integer)
    term_type: Mapped[str] = mapped_column(String(20))  # TERM_TYPES
    term_unit: Mapped[str] = mapped_column(String(10), default="month")
    base_annual_fils: Mapped[int] = mapped_column(Integer)
    fee_schedule_version: Mapped[str] = mapped_column(String(20))
    fee_schedule_status: Mapped[str] = mapped_column(String(20), default="example")  # example | proposed | confirmed
    opt_out_refund_config_version: Mapped[str | None] = mapped_column(String(20))
    net_amount_fils: Mapped[int] = mapped_column(Integer)
    vat_rate_bp: Mapped[int] = mapped_column(Integer, default=500)
    vat_fils: Mapped[int] = mapped_column(Integer)
    gross_fils: Mapped[int] = mapped_column(Integer)
    amount_basis: Mapped[str] = mapped_column(String(10), default="net")
    proration_rule: Mapped[str | None] = mapped_column(String(20))
    billing_line_id: Mapped[str | None] = mapped_column(String(80))
    invoice_id: Mapped[str | None] = mapped_column(String(80))
    det_event_reference: Mapped[str | None] = mapped_column(String(80))
    source_event_id: Mapped[str | None] = mapped_column(String(80))
    allocation_basis_flag: Mapped[str | None] = mapped_column(String(30))  # ALLOCATION_BASES
    status: Mapped[str] = mapped_column(String(30), default="created")  # SUBSCRIPTION_STATUSES
    pending_billing_reason: Mapped[str | None] = mapped_column(String(40))
    held_reason: Mapped[str | None] = mapped_column(String(80))
    removed_from_cohort: Mapped[bool] = mapped_column(Boolean, default=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    service_mode: Mapped[str] = mapped_column(String(20), default="full")  # full | read_only (unpaid after grace)
    grace_until: Mapped[date | None] = mapped_column(Date)
    renewal_due_at: Mapped[date | None] = mapped_column(Date)
    renewed_subscription_id: Mapped[str | None] = mapped_column(String(40))
    ended_cause: Mapped[str | None] = mapped_column(String(60))
    ended_on: Mapped[date | None] = mapped_column(Date)
    notice_version_shown: Mapped[str | None] = mapped_column(String(20))
    language_shown: Mapped[str | None] = mapped_column(String(5))
    version: Mapped[int] = mapped_column(Integer, default=1)
    version_history: Mapped[list | None] = mapped_column(JSON)  # previous date/fee values while pending_billing
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SubscriptionStateHistory(Base):
    __tablename__ = "subscription_state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    event_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor_key: Mapped[str | None] = mapped_column(String(80))
    reason_code: Mapped[str | None] = mapped_column(String(80))


class BillingRequest(Base):
    """One billing line request per subscription term. Idempotency key = licence + subscription + period."""

    __tablename__ = "billing_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("br"))
    subscription_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    billing_period: Mapped[str] = mapped_column(String(30))  # start|end
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    reissue_counter: Mapped[int] = mapped_column(Integer, default=0)
    amount_snapshot_fils: Mapped[int] = mapped_column(Integer)  # net; same key different amount = conflict
    net_fils: Mapped[int] = mapped_column(Integer)
    vat_fils: Mapped[int] = mapped_column(Integer)
    gross_fils: Mapped[int] = mapped_column(Integer)
    line_type: Mapped[str] = mapped_column(String(40), default="smart_services_subscription")
    reference_field: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="requested")  # BILLING_STATUSES
    hold_reason: Mapped[str | None] = mapped_column(String(60))  # fixed list
    collection_status: Mapped[str] = mapped_column(String(30), default="not_collected")  # COLLECTION_STATUSES
    collected_fils: Mapped[int] = mapped_column(Integer, default=0)
    outstanding_fils: Mapped[int] = mapped_column(Integer, default=0)
    refunded_fils: Mapped[int] = mapped_column(Integer, default=0)
    receipt_reference: Mapped[str | None] = mapped_column(String(80))  # labelled 'payment reference'
    billing_line_id: Mapped[str | None] = mapped_column(String(80))
    invoice_id: Mapped[str | None] = mapped_column(String(80))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_date_source: Mapped[str | None] = mapped_column(String(30))  # invoice_date | billing_line_timestamp
    billing_line_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    adapter: Mapped[str] = mapped_column(String(20), default="manual")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    read_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_readback: Mapped[dict | None] = mapped_column(JSON)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pay"))
    payment_transaction_id: Mapped[str] = mapped_column(String(80), unique=True)
    payment_idempotency_key: Mapped[str | None] = mapped_column(String(120))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    amount_fils: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(10))  # PAYMENT_TYPES
    billing_line_id: Mapped[str | None] = mapped_column(String(80))
    invoice_id: Mapped[str | None] = mapped_column(String(80))
    invoice_lines: Mapped[list | None] = mapped_column(JSON)  # [{line_id, line_type, gross_fils}] when DET gives the invoice
    refund_reason: Mapped[str | None] = mapped_column(String(40))
    allocation_status: Mapped[str] = mapped_column(String(30), default="received_unallocated")
    channel: Mapped[str | None] = mapped_column(String(40))


class PaymentAllocation(Base):
    """Append-only allocation rows (alloc-v1). Later DET links add a superseding row; history is never edited."""

    __tablename__ = "payment_allocations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("alloc"))
    supersedes_allocation_id: Mapped[str | None] = mapped_column(String(40))
    allocated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    allocation_basis: Mapped[str] = mapped_column(String(30))  # ALLOCATION_BASES
    rule_version: Mapped[str] = mapped_column(String(20), default="alloc-v1")
    payment_transaction_id: Mapped[str] = mapped_column(String(80), index=True)
    billing_request_id: Mapped[str | None] = mapped_column(String(40), index=True)
    billing_line_id: Mapped[str | None] = mapped_column(String(80))
    amount_fils: Mapped[int] = mapped_column(Integer)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(10), default="payment")  # payment | refund


class ReconciliationItem(Base):
    __tablename__ = "billing_reconciliation_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rec"))
    type: Mapped[str] = mapped_column(String(40))  # RECONCILIATION_TYPES
    subscription_id: Mapped[str | None] = mapped_column(String(40), index=True)
    billing_request_id: Mapped[str | None] = mapped_column(String(40))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    period: Mapped[str | None] = mapped_column(String(30))
    sent_fils: Mapped[int | None] = mapped_column(Integer)
    readback_fils: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolution_reason: Mapped[str | None] = mapped_column(String(60))
    resolved_by_key: Mapped[str | None] = mapped_column(String(80))
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(255))


class BillingAdjustmentProposal(Base):
    """Draft only; a DET administrator decides. Never sent automatically; never an automatic refund."""

    __tablename__ = "billing_adjustment_proposals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("adj"))
    subscription_id: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by_key: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Case(Base):
    """Opt-out / refund case (one per subscription and action family); complaints are logged separately."""

    __tablename__ = "subscription_cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("case"))
    subscription_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(20))  # CASE_ACTIONS
    action_family: Mapped[str] = mapped_column(String(20))
    terms_version: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)  # subscription + action + terms_version + case_id
    reason_code: Mapped[str] = mapped_column(String(40))
    reason_config_version: Mapped[str] = mapped_column(String(20))
    free_text: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="draft")  # CASE_STATES
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_at: Mapped[date | None] = mapped_column(Date)  # shown only after DET confirms
    actor_key: Mapped[str | None] = mapped_column(String(80))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    language_shown: Mapped[str | None] = mapped_column(String(5))
    notice_version_shown: Mapped[str | None] = mapped_column(String(20))
    identity_assurance_level: Mapped[str | None] = mapped_column(String(10))
    reference_code: Mapped[str] = mapped_column(String(12))
    det_instruction_state: Mapped[str] = mapped_column(String(30), default="not_sent")  # DET_INSTRUCTION_STATES
    det_instruction_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    alert_id: Mapped[str | None] = mapped_column(String(40))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_reason: Mapped[str | None] = mapped_column(String(80))


class Complaint(Base):
    """Platform complaint log; DET owns the outcome and the SLA."""

    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cmp"))
    reference: Mapped[str] = mapped_column(String(12), unique=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str | None] = mapped_column(String(40))
    subscription_id: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40))  # from configuration: charge | opt_out | service_quality | other
    description: Mapped[str] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(String(5), default="ar")
    contact_channel: Mapped[str | None] = mapped_column(String(40))
    related_module: Mapped[str | None] = mapped_column(String(40))
    related_date: Mapped[date | None] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reply_by: Mapped[date] = mapped_column(Date)
    interim_due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="received")  # COMPLAINT_STATUSES
    status_reason_code: Mapped[str | None] = mapped_column(String(40))
    filed_by_key: Mapped[str | None] = mapped_column(String(80))
    filed_by_role: Mapped[str | None] = mapped_column(String(40))
    filed_for_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    k4_eligible: Mapped[bool] = mapped_column(Boolean, default=True)  # subscription/billing categories only
    sla_working_days: Mapped[int] = mapped_column(Integer, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WelcomeRun(Base):
    """First-run welcome (SC2) per identity and company: what was shown, which version, and the choices."""

    __tablename__ = "welcome_runs"
    __table_args__ = (UniqueConstraint("company_id", "actor_key", name="uq_welcome_company_actor"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wel"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    actor_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done | later
    language_choice: Mapped[str | None] = mapped_column(String(5))
    reminder_channel: Mapped[str | None] = mapped_column(String(20))  # portal | email | sms (stub)
    terms_version_shown: Mapped[str | None] = mapped_column(String(20))
    notice_version_shown: Mapped[str | None] = mapped_column(String(20))
    language_shown: Mapped[str | None] = mapped_column(String(5))
    identity_assurance_level: Mapped[str | None] = mapped_column(String(10))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
