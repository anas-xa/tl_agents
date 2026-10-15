"""Rule and Calendar Reference and deadline engine (E3-S2) plus the SC4 Obligation store.

* ``DeadlineRule``     one versioned rule row (key/value with legal instrument, effective dates, applicability basis).
* ``RuleChange``       audit entry for every rule change (who, when, old/new, source, confirmed-by).
* ``CalendarEntry``    holiday entries per jurisdiction (UAE-FEDERAL, DUBAI-GOV, FTA, DET), provisional | confirmed,
                       entered and approved by two different people.
* ``CalendarVersion``  per jurisdiction and year: version label, last check date (stale after the configured age).
* ``Obligation``       one deadline per company and obligation key; statutory date stored beside the date used.
* ``FiledEvidence``    filed-evidence rows in source order (FTA status 1C, receipt 1A/1B, owner declaration).
* ``AuthorityDate``    FTA notice / portal status / authority extension override rows (dated, cited, one-off).
* ``RecalcBatch`` / ``RecalcCheckpoint``  recalculation batch with checkpoint (batch_id + company_id + calendar_version).
* ``NotifyOwnerRequest``  SC4 delegate 'Notify owner' (rate-limited once per 24 h per item).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

APPLICABILITY_BASES = ("period_end_date", "period_start_date", "event_date", "calculation_date")
RULE_STATUSES = ("draft", "active", "superseded")
RULE_SOURCE_TYPES = ("statutory", "authority notice", "DET record", "internal estimate")
RULE_DISPLAY_STATUSES = ("statutory date", "authority extension", "internal recommendation")
RULE_MANDATORY_FIELDS = ("key", "value", "legal_instrument", "effective_from", "effective_to", "version", "applicability_basis", "entered_by", "entered_date")
JURISDICTIONS = ("UAE-FEDERAL", "DUBAI-GOV", "FTA", "DET")
HOLIDAY_STATUSES = ("provisional", "confirmed")
OBLIGATION_TYPES = ("licence_renewal", "vat_return", "ct_return", "audit", "ejari_renewal", "other")
# Internal deadline source (E3-S2 Q318) and the SC4 contract enum (E1-S3 Q357, extended with ejari_record / owner_entered).
DEADLINE_SOURCES = ("FTA_NOTICE", "FTA_PORTAL_STATUS", "RULE_DERIVED", "DET", "EJARI", "OWNER_ENTERED")
DUE_DATE_SOURCES = ("fta_stated", "fta_extension", "rule_derived", "det_record", "ejari_record", "owner_entered")
DATE_STATUSES = ("confirmed", "not_confirmed")
READINESS = ("not_started", "data_missing", "draft_ready", "owner_approved", "receipt_recorded")
NONWORKING_FLAGS = ("none", "weekend", "public_holiday", "provisional_holiday")
RECALC_STATES = ("none", "recalculation_pending", "stale", "recalculation_failed")
FILED_SOURCES = ("fta_status", "receipt", "owner_declaration")
DATA_BASIS = ("based_on_details_you_entered", "based_on_verified_details")


class DeadlineRule(Base):
    __tablename__ = "deadline_rules"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_deadline_rule_key_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("drl"))
    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    legal_instrument: Mapped[str] = mapped_column(String(400))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)  # None = open-ended (explicitly given as 'open')
    version: Mapped[str] = mapped_column(String(20))
    applicability_basis: Mapped[str] = mapped_column(String(30), default="period_end_date")  # immutable after activation
    entered_by: Mapped[str] = mapped_column(String(120))
    entered_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # RULE_STATUSES
    confirmation_status: Mapped[str] = mapped_column(String(80), default="unconfirmed, source: none")
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(30), default="statutory")  # RULE_SOURCE_TYPES
    display_status: Mapped[str] = mapped_column(String(30), default="statutory date")  # RULE_DISPLAY_STATUSES
    label: Mapped[str | None] = mapped_column(String(255))
    last_checked: Mapped[date | None] = mapped_column(Date)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RuleChange(Base):
    __tablename__ = "deadline_rule_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[str] = mapped_column(String(120))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    new_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(400))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(20), default="created")  # created | activated | superseded


class CalendarEntry(Base):
    __tablename__ = "deadline_calendar_entries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("hol"))
    calendar_id: Mapped[str] = mapped_column(String(40), index=True)  # e.g. 'UAE-FEDERAL'
    jurisdiction: Mapped[str] = mapped_column(String(20), index=True)  # JURISDICTIONS
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    hijri_display_date: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="provisional")  # HOLIDAY_STATUSES
    source_reference: Mapped[str] = mapped_column(String(400))
    publication_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    entered_by: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))  # two-person approval: must differ from entered_by
    approval_state: Mapped[str] = mapped_column(String(20), default="pending_approval")  # pending_approval | approved | rejected
    loaded_by: Mapped[str] = mapped_column(String(120), default="manual entry")
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    version: Mapped[str] = mapped_column(String(20))


class CalendarVersion(Base):
    __tablename__ = "deadline_calendar_versions"
    __table_args__ = (UniqueConstraint("jurisdiction", "year", "version", name="uq_deadline_cal_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jurisdiction: Mapped[str] = mapped_column(String(20), index=True)
    year: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(20))
    source_reference: Mapped[str] = mapped_column(String(400))
    checked_at: Mapped[date] = mapped_column(Date)
    loaded_by: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Obligation(Base):
    __tablename__ = "deadline_obligations"
    __table_args__ = (UniqueConstraint("company_id", "obligation_key", name="uq_obligation_company_key"),)

    obligation_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("obl"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    obligation_key: Mapped[str] = mapped_column(String(160))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    obligation_type: Mapped[str] = mapped_column(String(30))  # OBLIGATION_TYPES
    subtype: Mapped[str | None] = mapped_column(String(40))  # e.g. chambers_membership
    authority: Mapped[str] = mapped_column(String(20), default="FTA")  # FTA | DET | EJARI | CHAMBERS
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_id: Mapped[str | None] = mapped_column(String(40))  # drafts/bookkeeping period id (2026-Q3, 2026-09, FY2026)
    statutory_date: Mapped[date | None] = mapped_column(Date)
    due_date_used: Mapped[date | None] = mapped_column(Date)
    deadline_source: Mapped[str] = mapped_column(String(30), default="RULE_DERIVED")  # DEADLINE_SOURCES
    due_date_source: Mapped[str] = mapped_column(String(30), default="rule_derived")  # DUE_DATE_SOURCES
    date_status: Mapped[str] = mapped_column(String(20), default="confirmed")  # DATE_STATUSES
    is_stated: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_version: Mapped[str | None] = mapped_column(String(40))
    calendar_version: Mapped[str | None] = mapped_column(String(80))
    calculation_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recommended_submit_by: Mapped[date | None] = mapped_column(Date)
    nonworking_flag: Mapped[str] = mapped_column(String(30), default="none")
    holiday_calendar_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    data_basis: Mapped[str] = mapped_column(String(40), default="based_on_details_you_entered")
    input_source: Mapped[str] = mapped_column(String(40), default="owner_entered")  # FTA | owner_confirmed | delegate_entered | unconfirmed | det | ejari
    recalc_state: Mapped[str] = mapped_column(String(30), default="none")
    last_confirmed_date: Mapped[date | None] = mapped_column(Date)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    provisional_date: Mapped[date | None] = mapped_column(Date)  # owner-entered or last known date when not confirmed
    filed_state: Mapped[str | None] = mapped_column(String(40))  # filed_fta_status | filed_receipt | owner_declared_unverified | status_unconfirmed
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_items: Mapped[list | None] = mapped_column(JSON)
    history: Mapped[list | None] = mapped_column(JSON)  # [{at, statutory_date, due_date_used, source, rule_version, calendar_version}]
    date_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    old_date: Mapped[date | None] = mapped_column(Date)
    date_change_source: Mapped[str | None] = mapped_column(String(40))
    readiness_fixture: Mapped[str | None] = mapped_column(String(30))  # demo-only readiness, labelled 'Demo data'
    input_hash: Mapped[str | None] = mapped_column(String(64))
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FiledEvidence(Base):
    __tablename__ = "deadline_filed_evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fev"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    obligation_key: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(30))  # FILED_SOURCES
    filing_reference: Mapped[str | None] = mapped_column(String(80))
    filed_date: Mapped[date | None] = mapped_column(Date)
    recorded_by_key: Mapped[str | None] = mapped_column(String(64))
    recorded_by_role: Mapped[str | None] = mapped_column(String(40))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthorityDate(Base):
    __tablename__ = "deadline_authority_dates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    obligation_key: Mapped[str] = mapped_column(String(160), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # FTA_NOTICE | FTA_PORTAL_STATUS | fta_extension
    stated_date: Mapped[date] = mapped_column(Date)
    instrument_reference: Mapped[str | None] = mapped_column(String(255))
    evidence_ref: Mapped[str | None] = mapped_column(String(80))  # held evidence (document id / manual reference)
    entered_by_key: Mapped[str | None] = mapped_column(String(64))
    entered_by_role: Mapped[str | None] = mapped_column(String(40))
    label: Mapped[str | None] = mapped_column(String(80))  # 'authority extension'
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class RecalcBatch(Base):
    __tablename__ = "deadline_recalc_batches"

    batch_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rcb"))
    calendar_version: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | finished | finished_with_failures
    company_order: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RecalcCheckpoint(Base):
    __tablename__ = "deadline_recalc_checkpoints"
    __table_args__ = (UniqueConstraint("batch_id", "company_id", "calendar_version", name="uq_recalc_checkpoint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    calendar_version: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class NotifyOwnerRequest(Base):
    __tablename__ = "deadline_notify_owner"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    item_code: Mapped[str] = mapped_column(String(40))
    requested_by_key: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
