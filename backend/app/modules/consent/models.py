"""Consent store (E4-S1) and withdrawal enforcement records (E4-S2).

One consent record per company x source x accounts x purpose; a new version supersedes the previous one.
Every status transition is one-way except Active -> Superseded. The gate (``service.check_consent``) is the
only path through which other modules may read data under consent, and it fails closed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

CONSENT_TYPES = (
    "bank_data_open_finance",  # bank data through the licensed Open Finance provider (consent journey is the provider's)
    "ledger_invoice_authorisation",  # ledger and invoice data authorisation (ERP connector and file uploads)
    "tax_data",  # tax registration and filing status data (FTA route open)
    "auditor_specialist_evidence_access",  # case-specific evidence access for the assigned auditor or specialist
)
SOURCES = ("bank", "erp", "tax_authority", "e_invoice_provider")
TYPE_SOURCE = {
    "bank_data_open_finance": "bank",
    "ledger_invoice_authorisation": "erp",
    "tax_data": "tax_authority",
}
STATUSES = (
    "pending",  # waiting for the bank or provider to confirm; no data read; cancel allowed
    "active",
    "paused",  # status_reason: licence_expired | subscription_ended (Q47)
    "expired",  # evaluated in Asia/Dubai; also pause-limit lapse (status_reason pause_limit_exceeded)
    "withdrawn_on_platform",  # Q52 sub-status 1
    "revocation_confirmed_by_provider",  # Q52 sub-status 2
    "superseded",  # version state only
)
PAUSE_REASONS = ("licence_expired", "subscription_ended")
GRANTOR_ROLES = ("owner", "delegate")
GRANTOR_CAPACITIES = ("authorised_signatory", "attorney")
# K13 classes (Q378)
K13_CLASSES = ("normal", "no_scheduled_pulls", "unenforced_open")
PROVIDER_REVOCATION_STATUSES = ("not_applicable", "pending", "retrying", "failed", "confirmed")
DATA_USE_FLAGS = ("active", "stopped")
NOTIFICATION_CHANNELS = ("portal", "email")


class Consent(Base):
    __tablename__ = "consents"

    consent_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cns"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(50))  # CONSENT_TYPES
    source: Mapped[str] = mapped_column(String(30))  # SOURCES
    provider_name: Mapped[str | None] = mapped_column(String(120))  # bank / provider / system name (Latin script isolated in UI)
    data_types: Mapped[list] = mapped_column(JSON, default=list)
    account_ids: Mapped[list] = mapped_column(JSON, default=list)  # masked in the UI (last 4)
    purpose: Mapped[str] = mapped_column(String(60))
    recipient: Mapped[str | None] = mapped_column(String(80))  # evidence access: engagement or case reference
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    route_limit_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    list_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="pending")  # STATUSES
    status_reason: Mapped[str | None] = mapped_column(String(60))
    grantor_identity_uuid: Mapped[str | None] = mapped_column(String(64))
    grantor_display_name: Mapped[str | None] = mapped_column(String(255))
    grantor_role: Mapped[str] = mapped_column(String(20), default="owner")
    grantor_capacity: Mapped[str] = mapped_column(String(40), default="authorised_signatory")
    capacity_document_ref: Mapped[str | None] = mapped_column(String(120))
    identity_assurance_level: Mapped[str | None] = mapped_column(String(10))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    granting_owner_uuid: Mapped[str | None] = mapped_column(String(64))
    granting_owner_name: Mapped[str | None] = mapped_column(String(255))
    delegation_id: Mapped[str | None] = mapped_column(String(40))
    granted_by_removed_delegate: Mapped[bool] = mapped_column(Boolean, default=False)
    external_consent_id: Mapped[str | None] = mapped_column(String(80))
    external_status: Mapped[str | None] = mapped_column(String(40))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), index=True)
    scope_key: Mapped[str] = mapped_column(String(64), index=True)  # company+source+accounts+purpose (+recipient)
    wording_version: Mapped[str | None] = mapped_column(String(40))
    audit_entry_ref: Mapped[str | None] = mapped_column(String(40))
    receipt_ref: Mapped[str | None] = mapped_column(String(40))
    superseded_by: Mapped[str | None] = mapped_column(String(40))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ConsentReceipt(Base):
    """Immutable receipt with the exact wording shown (grant or withdrawal), bilingual."""

    __tablename__ = "consent_receipts"

    receipt_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rcp"))
    receipt_number: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # grant | withdrawal
    consent_id: Mapped[str] = mapped_column(ForeignKey("consents.consent_id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    template_version: Mapped[str] = mapped_column(String(40))
    wording_version: Mapped[str | None] = mapped_column(String(40))
    content_en: Mapped[dict] = mapped_column(JSON)
    content_ar: Mapped[dict] = mapped_column(JSON)
    audit_entry_ref: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConsentWithdrawal(Base):
    """Withdrawal record with the three timestamps written by three services (Q378)."""

    __tablename__ = "consent_withdrawals"

    withdrawal_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wdr"))
    consent_id: Mapped[str] = mapped_column(ForeignKey("consents.consent_id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    withdrawn_at: Mapped[datetime] = mapped_column(DateTime)  # written by the consent registry
    withdrawer_identity_uuid: Mapped[str | None] = mapped_column(String(64))
    withdrawer_display_name: Mapped[str | None] = mapped_column(String(255))
    withdrawer_role: Mapped[str | None] = mapped_column(String(20))
    scope: Mapped[str] = mapped_column(String(20), default="whole")  # whole | partial (1B)
    platform_status: Mapped[str] = mapped_column(String(40), default="withdrawn_on_platform")
    provider_revocation_status: Mapped[str] = mapped_column(String(20), default="not_applicable")
    revocation_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    manual_ticket_ref: Mapped[str | None] = mapped_column(String(40))
    revocation_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    jobs_cancelled: Mapped[int] = mapped_column(Integer, default=0)
    pulls_stopped_at: Mapped[datetime | None] = mapped_column(DateTime)  # written by the ingestion orchestrator
    last_blocked_call_at: Mapped[datetime | None] = mapped_column(DateTime)
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    deletion_due_at: Mapped[datetime | None] = mapped_column(DateTime)
    deletion_done_at: Mapped[datetime | None] = mapped_column(DateTime)  # written by the deletion service (1C)
    records_restricted: Mapped[int] = mapped_column(Integer, default=0)
    records_on_legal_hold: Mapped[int] = mapped_column(Integer, default=0)
    drafts_marked_stale: Mapped[int] = mapped_column(Integer, default=0)
    k13_class: Mapped[str] = mapped_column(String(30), default="normal")
    receipt_ref: Mapped[str | None] = mapped_column(String(40))
    audit_entry_ref: Mapped[str | None] = mapped_column(String(40))
    ops_alert_raised: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GateToken(Base):
    """Per-request token handed to a connector after an Allow decision (lifetime <= 60 s)."""

    __tablename__ = "consent_gate_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    consent_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer)
    company_id: Mapped[str] = mapped_column(String(40))
    scope: Mapped[dict] = mapped_column(JSON)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class ConsentRequest(Base):
    """'Ask the owner for this right' / 'Request consent from the owner': logged, time-limited, grants nothing."""

    __tablename__ = "consent_requests"

    request_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("creq"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    requester_identity_uuid: Mapped[str] = mapped_column(String(64))
    requester_display_name: Mapped[str | None] = mapped_column(String(255))
    requester_role: Mapped[str] = mapped_column(String(20))
    consent_type: Mapped[str] = mapped_column(String(50))
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | expired | closed
    notified_count: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    """Minimal notices (in-portal record + email stub): type, date, status, link; never figures or identity numbers."""

    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ntf"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    recipient_identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    recipient_role: Mapped[str | None] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(10), default="portal")  # NOTIFICATION_CHANNELS
    kind: Mapped[str] = mapped_column(String(60))  # e.g. consent_withdrawn, consent_expiry_30d, pause, consent_request
    template_key: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(40))
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    body_en: Mapped[str] = mapped_column(Text)
    body_ar: Mapped[str] = mapped_column(Text)
    delivery_status: Mapped[str] = mapped_column(String(20), default="delivered")  # delivered | stub_queued | failed
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
