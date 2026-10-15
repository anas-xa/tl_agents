"""Tax calculation (E5-S2): entity profile, immutable versioned calculation results, adjustments, escalations."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

TAX_TYPES = ("vat", "ct")
CT_STATUSES = ("standalone_mainland", "tax_group", "qfzp", "unclear")
SBR_ELECTIONS = ("undecided", "elected", "not_elected")
CALC_STATES = ("current", "incomplete", "stale", "no_rule_stop", "run_failed", "blocked", "missing_vat_code")
REVIEW_STATUSES = ("not_reviewed", "reviewed")
ADJUSTMENT_CLASSES = ("calculated", "flagged", "person_entered")
SCOPE_BLOCK_WORDING = "This company is outside the pilot's supported scope; a specialist will contact you"
ESCALATED_STATUS = "escalated for specialist review"
DRAFT_LABEL = "Draft, not filed, not tax advice"


class TaxEntityProfile(Base):
    """Company tax profile used by E5 (TRN, period type, corporate-tax status, SBR election, revenue)."""

    __tablename__ = "tax_entity_profiles"

    company_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    trn: Mapped[str | None] = mapped_column(String(20))
    vat_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_period_type: Mapped[str] = mapped_column(String(10), default="quarterly")  # quarterly | monthly
    ct_status: Mapped[str] = mapped_column(String(30), default="unclear")  # CT_STATUSES
    ct_status_source: Mapped[str] = mapped_column(String(60), default="self-declared, unverified")
    financial_year_end_month: Mapped[int] = mapped_column(Integer, default=12)
    financial_year_end_day: Mapped[int] = mapped_column(Integer, default=31)
    first_ct_period_start: Mapped[date | None] = mapped_column(Date)
    sbr_election: Mapped[str] = mapped_column(String(20), default="undecided")  # SBR_ELECTIONS
    revenue_fils: Mapped[int | None] = mapped_column(Integer)
    revenue_source: Mapped[str | None] = mapped_column(String(120))  # e.g. "books (IFRS for SMEs), owner to confirm"
    revenue_confirmed_by: Mapped[str | None] = mapped_column(String(120))
    revenue_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    related_party_declared: Mapped[bool] = mapped_column(Boolean, default=False)
    mne_group_eur_750m: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxPeriodRevenue(Base):
    """Accounting revenue per tax period (owner- or signatory-confirmed), for the SBR 'all previous periods' test."""

    __tablename__ = "tax_period_revenues"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rev"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    revenue_fils: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="books, owner to confirm")
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class CalculationResult(Base):
    """Versioned, immutable calculation result. Old versions are kept, never overwritten."""

    __tablename__ = "tax_calculations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("calc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    tax_type: Mapped[str] = mapped_column(String(5))  # TAX_TYPES
    period_id: Mapped[str] = mapped_column(String(40), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    rule_version: Mapped[str | None] = mapped_column(String(120))  # rule ids and versions used
    current_rule_version: Mapped[str | None] = mapped_column(String(120))
    rule_refs: Mapped[dict | None] = mapped_column(JSON)  # rule id -> {version, instrument, effective_from, status, confirmed_by}
    inputs: Mapped[dict | None] = mapped_column(JSON)
    inputs_source: Mapped[dict | None] = mapped_column(JSON)  # input -> company-entered | classified
    ai_prepared: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(20), default="not_reviewed")
    reviewed_by_name: Mapped[str | None] = mapped_column(String(120))
    reviewed_by_role: Mapped[str | None] = mapped_column(String(40))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(20), default="current")  # CALC_STATES
    state_reason: Mapped[str | None] = mapped_column(Text)
    excluded_items: Mapped[list | None] = mapped_column(JSON)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_total_fils: Mapped[int] = mapped_column(Integer, default=0)
    outputs: Mapped[dict | None] = mapped_column(JSON)
    trace: Mapped[list | None] = mapped_column(JSON)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_date_source: Mapped[str | None] = mapped_column(String(40))  # authority | user_confirmed | computed
    data_hash: Mapped[str | None] = mapped_column(String(64))
    escalation_ids: Mapped[list | None] = mapped_column(JSON)
    notification_ref: Mapped[str | None] = mapped_column(String(20))  # no-rule stop
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    label: Mapped[str] = mapped_column(String(80), default=DRAFT_LABEL)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_key: Mapped[str | None] = mapped_column(String(64))


class Adjustment(Base):
    """Corporate-tax adjustment: calculated | flagged | person-entered (with reason and person)."""

    __tablename__ = "tax_adjustments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("adj"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    period_id: Mapped[str] = mapped_column(String(40), index=True)
    adjustment_class: Mapped[str] = mapped_column(String(20))  # ADJUSTMENT_CLASSES
    kind: Mapped[str] = mapped_column(String(60))  # exempt_income | non_deductible | interest_limit | related_party | ...
    label: Mapped[str] = mapped_column(String(160))
    amount_fils: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    related_party: Mapped[bool] = mapped_column(Boolean, default=False)
    entered_by_name: Mapped[str | None] = mapped_column(String(120))
    entered_by_role: Mapped[str | None] = mapped_column(String(40))
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    review_status: Mapped[str] = mapped_column(String(40), default="person-entered, not reviewed")
    held_for_specialist: Mapped[bool] = mapped_column(Boolean, default=False)


class EscalationRecord(Base):
    """K21 escalation record created by a trigger (1-5) or a scope block."""

    __tablename__ = "tax_escalations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("esc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    tax_type: Mapped[str] = mapped_column(String(5))
    period_id: Mapped[str] = mapped_column(String(40))
    calculation_id: Mapped[str | None] = mapped_column(String(40))
    trigger_id: Mapped[str] = mapped_column(String(10))  # 1..5 | scope | manual
    amount_fils: Mapped[int | None] = mapped_column(Integer)
    rule_version: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default=ESCALATED_STATUS)
    expected_response_hours: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_key: Mapped[str | None] = mapped_column(String(64))
