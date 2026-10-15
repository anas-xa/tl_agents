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
LICENCE_STATUSES = ("active", "expired", "suspended", "cancelled", "under_renewal")
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
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
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
