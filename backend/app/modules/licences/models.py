"""DET trade licence records, persons and intake events (E2-S1).

Intake is a configurable mapping: in scope means DET authority, mainland type and a DET licence number.
Unmapped or unclassified values are held for review and never billed or reminded.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

# Platform (normalised) licence statuses: five statuses per the intake decision.
LICENCE_STATUSES = ("active", "expired", "suspended", "cancelled", "under_renewal", "unknown")
# Scope result of the in-scope test (DET authority + mainland + DET licence number). Unclassified is held for
# review and never billed or reminded.
SCOPES = ("in_scope", "out_of_scope", "unclassified_held_for_review")
# Intake outcome of one DET event.
EVENT_STATUSES = ("received", "processed", "duplicate_ignored", "quarantined", "held_for_review")
QUARANTINE_REASONS = ("missing_reference", "reference_conflict")
HOLD_REASONS = (
    "unmapped_event_type",
    "unmapped_status",
    "unclassified_authority",
    "out_of_scope_licence",
    "correction_expiry_earlier",
    "out_of_order_replay",
    "licence_not_linked",
    "renewal_not_completed",
)
# Event-type precedence for same-day ties (issuance, renewal, amendment, suspension, cancellation).
EVENT_PRECEDENCE = {"issued": 0, "renewed": 1, "amended": 2, "reinstated": 3, "suspended": 4, "expired": 5, "cancelled": 6, "transferred": 7}
# K6 classes (rule k6-v1, provisional until DET confirms renewal semantics).
K6_CLASSES = ("on_time", "late_within_grace", "late", "excluded", "not_applicable")
# Eight event types per the intake decision.
LICENCE_EVENT_TYPES = (
    "issued",
    "renewed",
    "amended",
    "expired",
    "suspended",
    "reinstated",
    "cancelled",
    "transferred",
)
AUTHORITIES = ("DET",)
LICENCE_TYPES = ("mainland",)


class Licence(Base):
    __tablename__ = "licences"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lic"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)  # None until linked (pending match)
    licence_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    issuing_authority: Mapped[str] = mapped_column(String(20), default="DET")
    licence_type: Mapped[str] = mapped_column(String(20), default="mainland")
    trade_name_en: Mapped[str] = mapped_column(String(255))
    trade_name_ar: Mapped[str] = mapped_column(String(255))
    legal_form: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(80))
    activities: Mapped[list | None] = mapped_column(JSON)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    previous_expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # LICENCE_STATUSES
    raw_status: Mapped[str | None] = mapped_column(String(80))  # DET raw value before mapping
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    scope: Mapped[str] = mapped_column(String(40), default="in_scope")  # SCOPES
    out_of_scope_reason: Mapped[str | None] = mapped_column(String(120))
    renewal_state: Mapped[str | None] = mapped_column(String(40))  # separate from legal status (expired-in-grace != cancelled)
    term_start_date: Mapped[date | None] = mapped_column(Date)
    status_mapping_version: Mapped[str | None] = mapped_column(String(20))
    held_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    held_reason: Mapped[str | None] = mapped_column(String(120))
    ejari_number: Mapped[str | None] = mapped_column(String(40))
    ejari_expiry: Mapped[date | None] = mapped_column(Date)
    ejari_status: Mapped[str | None] = mapped_column(String(20))  # verified | owner_declared | unconfirmed | not_applicable
    premises: Mapped[str | None] = mapped_column(String(255))
    chamber_membership_status: Mapped[str | None] = mapped_column(String(20))
    chamber_membership_expiry: Mapped[date | None] = mapped_column(Date)
    last_det_refresh_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LicencePerson(Base):
    """Partner, manager or authorised signatory on the DET record (identity matched by hashed Emirates ID)."""

    __tablename__ = "licence_persons"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lp"))
    licence_id: Mapped[str] = mapped_column(ForeignKey("licences.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    capacity: Mapped[str] = mapped_column(String(40))  # owner | partner | manager | authorised_signatory | attorney
    emirates_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    has_emirates_id: Mapped[bool] = mapped_column(Boolean, default=True)
    share_percent: Mapped[float | None] = mapped_column()
    signing_rule: Mapped[str | None] = mapped_column(String(20))  # any_one | joint | unclear
    source_document: Mapped[str | None] = mapped_column(String(120))
    valid_to: Mapped[date | None] = mapped_column(Date)


class LicenceEvent(Base):
    __tablename__ = "licence_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True)  # DET event id (idempotency key)
    licence_id: Mapped[str | None] = mapped_column(ForeignKey("licences.id"), index=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str | None] = mapped_column(String(20))  # LICENCE_EVENT_TYPES; None when unmapped
    raw_event_type: Mapped[str | None] = mapped_column(String(80))
    effective_date: Mapped[date | None] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    payload: Mapped[dict | None] = mapped_column(JSON)
    held_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    held_reason: Mapped[str | None] = mapped_column(String(120))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    renewal_completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    previous_expiry_date: Mapped[date | None] = mapped_column(Date)
    new_expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    # E2-S1 intake extension
    det_reference: Mapped[str | None] = mapped_column(String(80), index=True)
    det_sequence: Mapped[int | None] = mapped_column(Integer)
    det_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    arrival_order: Mapped[int | None] = mapped_column(Integer)
    det_event_date: Mapped[date | None] = mapped_column(Date)
    payment_received_at: Mapped[datetime | None] = mapped_column(DateTime)  # stored, never a renewal signal
    new_term_start_date: Mapped[date | None] = mapped_column(Date)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), index=True)  # licence + type + reference (or term start)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="received")  # EVENT_STATUSES
    quarantine_reason: Mapped[str | None] = mapped_column(String(40))  # QUARANTINE_REASONS
    raw_status: Mapped[str | None] = mapped_column(String(80))
    mapped_status: Mapped[str | None] = mapped_column(String(20))
    k6_class: Mapped[str | None] = mapped_column(String(30))  # K6_CLASSES
    k6_rule_version: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(40))  # det_feed | manual_file | staff | demo
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)


class LicenceHistory(Base):
    """Previous values of licence fields, kept for the configured window; source is always 'Read from DET'."""

    __tablename__ = "licence_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    licence_id: Mapped[str] = mapped_column(ForeignKey("licences.id"), index=True)
    field: Mapped[str] = mapped_column(String(60))
    previous_value: Mapped[str | None] = mapped_column(String(255))
    current_value: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(40), default="Read from DET")
    event_id: Mapped[str | None] = mapped_column(String(80))


class LicenceEventOutbox(Base):
    """Queue message written after a licence event is committed (E2-S2 consumes it; never the reverse)."""

    __tablename__ = "licence_event_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(255))
    dead_letter: Mapped[bool] = mapped_column(Boolean, default=False)
