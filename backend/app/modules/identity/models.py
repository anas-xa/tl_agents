"""Identity, sessions, staff roles and pending sign-ins (E1-S1).

Stored per decision: identity UUID, assurance level, profile type, DET match result, display name.
The Emirates ID number is never stored.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.time import utcnow

ASSURANCE_LEVELS = ("SOP1", "SOP2", "SOP3")
PROFILE_TYPES = {1: "resident_or_citizen", 2: "visitor"}
STAFF_ROLES = (
    "det_admin",
    "det_pilot_manager",
    "det_complaint_handler",
    "det_compliance_lead",
    "compliance_reviewer",
    "licensed_auditor",
    "tax_specialist",
    "legal_specialist",
    "escalation_ops",
    "platform_security_admin",
    "qeonix_product_owner",
    "qeonix_audit_ops",
)
# Roles that are exclusive of each other (held globally): DET administrator and compliance reviewer.
EXCLUSIVE_STAFF_PAIRS = {frozenset({"det_admin", "compliance_reviewer"})}
SIGNIN_REASON_CODES = (
    "LEVEL_TOO_LOW",
    "STATE_INVALID",
    "STATE_EXPIRED",
    "ASSERTION_INVALID",
    "DET_MATCH_FAIL",
    "NO_COMPANY_ROLE",
    "AUDIT_UNAVAILABLE",
    "CANCELLED",
    "PROVIDER_UNAVAILABLE",
)


class Identity(Base):
    __tablename__ = "identities"

    uuid: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    assurance_level: Mapped[str] = mapped_column(String(10))
    profile_type: Mapped[int] = mapped_column(Integer, default=1)
    det_match_result: Mapped[str] = mapped_column(String(20), default="unmatched")  # matched | unmatched | no_emirates_id
    language: Mapped[str] = mapped_column(String(5), default="en")
    numerals: Mapped[str] = mapped_column(String(10), default="western")  # western | arabic_indic
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_mobile: Mapped[str | None] = mapped_column(String(40))
    privacy_notice_seen_version: Mapped[str | None] = mapped_column(String(20))
    first_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StaffRole(Base):
    """Staff-role table, changed only through the two-person administration function (Q4)."""

    __tablename__ = "staff_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)  # bound on first sign-in
    role: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str | None] = mapped_column(String(120))  # e.g. 'det', 'qeonix', firm id
    work_email: Mapped[str] = mapped_column(String(255))
    invitation_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="invited")  # invited | active | removed | expired
    requester: Mapped[str] = mapped_column(String(120))
    approver: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text)
    entitlement_ref: Mapped[str | None] = mapped_column(String(80))  # specialist entitlement register id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PendingSignIn(Base):
    __tablename__ = "pending_signins"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    return_to: Mapped[str | None] = mapped_column(String(255))


class UserSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_reason: Mapped[str | None] = mapped_column(String(40))  # sign_out | idle_timeout | max_length | revoked
    language: Mapped[str] = mapped_column(String(5), default="en")
    assurance_level: Mapped[str] = mapped_column(String(10))
    config_version: Mapped[str | None] = mapped_column(String(40))
    step_up_at: Mapped[datetime | None] = mapped_column(DateTime)  # last UAE PASS step-up for approval acts
    client_meta: Mapped[dict | None] = mapped_column(JSON)


class SignInFailureCounter(Base):
    """Rolling failure counters for the operational alert (Q3)."""

    __tablename__ = "signin_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(50))
    reason_code: Mapped[str] = mapped_column(String(40))


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    alert_type: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20), default="high")
    recipients: Mapped[list] = mapped_column(JSON)
    details: Mapped[dict | None] = mapped_column(JSON)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
