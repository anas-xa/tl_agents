"""Companies and company-scoped roles.

A company has a stable internal id; licence numbers, trade names and TRNs may change over time
(data risk: duplicate and changed identities), so the licence history lives in the licences module.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

COMPANY_ROLES = ("owner", "remote_owner", "delegate", "licensed_auditor", "specialist", "compliance_reviewer")
ROLE_STATUSES = ("invited", "active", "suspended", "revoked", "expired")
# Delegate rights that are built but switched off in the pilot (Phase B): grant_consent, approve_submissions,
# change_subscription. Phase A rights: prepare, view.
DELEGATE_RIGHTS = ("prepare", "view", "grant_consent", "approve_submissions", "change_subscription")
CAPACITIES = ("owner", "authorised_manager", "authorised_signatory", "attorney", "delegate", "staff")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("co"))
    trade_name_en: Mapped[str] = mapped_column(String(255))
    trade_name_ar: Mapped[str] = mapped_column(String(255))
    legal_form: Mapped[str | None] = mapped_column(String(80))
    owner_location_self_declared: Mapped[str | None] = mapped_column(String(20))  # 'uae' | 'abroad' | None
    financial_year_end_month: Mapped[int] = mapped_column(Integer, default=12)
    financial_year_end_day: Mapped[int] = mapped_column(Integer, default=31)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    onboarding_at: Mapped[datetime | None] = mapped_column(DateTime)
    onboarding_id: Mapped[str | None] = mapped_column(String(40))
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    related_entity_group: Mapped[str | None] = mapped_column(String(40))  # e.g. tax group id, for auditor firewall


class CompanyRole(Base):
    """A role held by an identity on one company (roles are always held per company)."""

    __tablename__ = "company_roles"
    __table_args__ = (UniqueConstraint("identity_uuid", "company_id", "role", name="uq_identity_company_role"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cr"))
    identity_uuid: Mapped[str | None] = mapped_column(String(64), index=True)  # null while invited
    invitation_email: Mapped[str | None] = mapped_column(String(255))
    invitation_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))  # COMPANY_ROLES
    capacity: Mapped[str] = mapped_column(String(40), default="owner")  # CAPACITIES
    status: Mapped[str] = mapped_column(String(20), default="active")  # ROLE_STATUSES
    functions: Mapped[list | None] = mapped_column(JSON)  # delegate functions assigned by the owner
    rights: Mapped[list | None] = mapped_column(JSON)  # DELEGATE_RIGHTS granted (Phase B rights stay off)
    granted_by_uuid: Mapped[str | None] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_to: Mapped[date | None] = mapped_column(Date)
    authority_evidence_ref: Mapped[str | None] = mapped_column(String(80))  # authority evidence record id
    independence_declared_at: Mapped[datetime | None] = mapped_column(DateTime)  # licensed auditor
    reconfirm_by: Mapped[date | None] = mapped_column(Date)  # 30-day reconfirmation window (view-only)
    suspended_reason: Mapped[str | None] = mapped_column(String(80))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    is_internal_test: Mapped[bool] = mapped_column(Boolean, default=False)
