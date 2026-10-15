"""Phase map, gate register and integration go-live checklist (E1-S7, E1-S8). Registers are append-only."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

INCREMENT_IDS = ("1A", "1B", "1C", "1D")
INCREMENT_STATUSES = ("not_started", "in_build", "manual_path_live", "live", "demo_done")
GATE_PANEL_STATUSES = ("not_met", "in_progress", "met", "not_needed_in_pilot")
GATE_REGISTER_STATUSES = ("not_yet_confirmed", "evidence_received", "open", "closed", "fallback_active", "not_needed_in_pilot")
GATE_TYPES = ("entry_gate", "fallback")
INTEGRATION_ROWS = ("FTA", "bank", "ERP", "DET_billing", "auditor_register", "manual_upload", "none")
INTEGRATIONS = ("FTA", "bank", "ERP", "DET_billing", "auditor_register", "manual_upload", "e_invoicing_provider", "payment_channel", "uae_pass", "det_licence_feed", "signed_audit")
ROW_STATUSES = ("not_yet_confirmed", "evidence_pending", "confirmed_live", "switched_off", "expired")
ITEM_TYPES = ("precondition", "fallback", "go_live_evidence")
SWITCH_STATES = ("ON", "OFF")


class Increment(Base):
    __tablename__ = "phase_increments"

    id: Mapped[str] = mapped_column(String(4), primary_key=True)  # INCREMENT_IDS
    order: Mapped[int] = mapped_column(Integer)
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    entry_gate_en: Mapped[str] = mapped_column(String(255))
    entry_gate_ar: Mapped[str] = mapped_column(String(255))
    manual_fallback_en: Mapped[str] = mapped_column(String(255))
    manual_fallback_ar: Mapped[str] = mapped_column(String(255))
    demo_outcome_en: Mapped[str] = mapped_column(Text)
    demo_outcome_ar: Mapped[str] = mapped_column(Text)
    stories: Mapped[list | None] = mapped_column(JSON)  # ordered [{order, story_id, title, gated: bool}]
    manual_path: Mapped[list | None] = mapped_column(JSON)
    gated: Mapped[list | None] = mapped_column(JSON)
    functions: Mapped[list | None] = mapped_column(JSON)  # delegate functions this increment serves
    build_state: Mapped[str] = mapped_column(String(20), default="not_started")  # not_started | in_build | built
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    released_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GateRegisterRow(Base):
    """One row per gate per version (append-only). Current = latest version."""

    __tablename__ = "gate_register"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gt"))
    gate_id: Mapped[str] = mapped_column(String(60), index=True)
    increment: Mapped[str] = mapped_column(String(4))
    story_id: Mapped[str | None] = mapped_column(String(20))
    gate_type: Mapped[str] = mapped_column(String(20), default="entry_gate")  # GATE_TYPES
    integration_row: Mapped[str] = mapped_column(String(30), default="none")  # INTEGRATION_ROWS
    description_en: Mapped[str] = mapped_column(String(255))
    description_ar: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="not_yet_confirmed")  # GATE_REGISTER_STATUSES
    fallback_path: Mapped[str | None] = mapped_column(String(255))
    required_evidence_list: Mapped[list | None] = mapped_column(JSON)
    evidence_refs: Mapped[list | None] = mapped_column(JSON)  # references only, no company data
    evidence_provided_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime)
    changed_by: Mapped[str | None] = mapped_column(String(120))  # actor key + role
    change_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(120))  # owner identity, required to open
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DemoRecord(Base):
    """'Demo done' is recorded by the product owner, never inferred."""

    __tablename__ = "phase_demo_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("demo"))
    increment: Mapped[str] = mapped_column(String(4), index=True)
    criteria: Mapped[dict | None] = mapped_column(JSON)  # {a,b,c,d: bool}
    gated_items_shown_off: Mapped[list | None] = mapped_column(JSON)
    recorded_by: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text)


class IntegrationChecklistRow(Base):
    """Go-live checklist row per integration (append-only versions; current = latest)."""

    __tablename__ = "integration_checklist"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("icr"))
    row_id: Mapped[str] = mapped_column(String(40), index=True)  # fta | bank_<code> | erp | det_billing | ...
    integration: Mapped[str] = mapped_column(String(30))  # INTEGRATIONS
    name_en: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[str] = mapped_column(String(160))
    switch_key: Mapped[str] = mapped_column(String(60))
    bank_code: Mapped[str | None] = mapped_column(String(40))
    phase: Mapped[int] = mapped_column(Integer, default=1)  # 1 manual upload... 4 signed audit
    fallback_path: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="not_yet_confirmed")  # ROW_STATUSES
    items: Mapped[list | None] = mapped_column(JSON)  # [{item_id,text_en,text_ar,item_type,tag,owner_name,owner_role,evidence_reference,evidence_date,approver_identity,approved_at,evidence_expires_at}]
    evidence_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    mock: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[str | None] = mapped_column(String(40))
    changed_by: Mapped[str | None] = mapped_column(String(120))
    change_reason: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationSwitch(Base):
    __tablename__ = "integration_switches"

    switch_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    row_id: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(3), default="OFF")  # SWITCH_STATES
    changed_by: Mapped[str | None] = mapped_column(String(120))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    change_reason: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list | None] = mapped_column(JSON)  # [{state, changed_by, changed_at, reason}]
