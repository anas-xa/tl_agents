"""UAE hosting, encryption and local-model guardrails (E1-S4): residency inventory, release decisions,
checklist document, key register, egress policy changes and alerts, and the K12 onboarding link events.

All timestamps naive UTC. No company financial data or identity numbers are stored in these tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

COMPONENT_TYPES = ("compute", "storage", "backup", "log", "monitoring", "key", "ai_model", "queue", "database", "other")
HOSTING_LOCATIONS = ("UAE region", "Dubai Government cloud / DESC-accredited", "unknown")
UAE_LOCATIONS = ("UAE region", "Dubai Government cloud / DESC-accredited")
COMPONENT_STATUSES = ("pass", "fail", "pending")
RELEASE_RESULTS = ("pass", "blocked")
GENERATOR_STATUSES = ("ok", "failed", "timed_out", "unavailable")
KEY_TYPES = ("kek", "dek", "service_credential", "tls_cert")
KEY_STATUSES = ("active", "rewrapping", "retired")
ROTATION_STEPS = ("new_version_created", "rewrap_started", "rewrap_completed", "old_version_retired")
CHANGE_STATUSES = ("pending", "approved", "applied", "expired", "withdrawn", "superseded")
ALERT_STATUSES = ("open", "acknowledged", "escalated")
LINK_TYPES = ("det_licence_record", "fta_tax_profile", "fta_profile_manual", "bank_feed", "ledger_connection", "manual_upload")
# 'requested' is a non-counting pending marker (bank waiting for confirmation); it never makes a link active.
LINK_EVENT_TYPES = ("activated", "deactivated", "revoked", "expired", "reactivated", "requested")
COHORT_STATUSES = ("open", "closed", "exited")


class ResidencyInventory(Base):
    """One generated inventory version (the deployment register snapshot)."""

    __tablename__ = "residency_inventories"

    inventory_version: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inv"))
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    generator_status: Mapped[str] = mapped_column(String(20), default="ok")  # GENERATOR_STATUSES
    checklist_version: Mapped[str] = mapped_column(String(20), default="v1")
    check_mode: Mapped[str] = mapped_column(String(60), default="UAE region")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    variant: Mapped[str | None] = mapped_column(String(40))  # demo variant label
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResidencyComponent(Base):
    __tablename__ = "residency_components"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cmp"))
    inventory_version: Mapped[str] = mapped_column(ForeignKey("residency_inventories.inventory_version"), index=True)
    component_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    component_type: Mapped[str] = mapped_column(String(20))  # COMPONENT_TYPES
    data_types: Mapped[list | None] = mapped_column(JSON)
    hosting_location: Mapped[str] = mapped_column(String(60), default="unknown")  # HOSTING_LOCATIONS
    operator: Mapped[str | None] = mapped_column(String(120))
    jurisdiction: Mapped[str | None] = mapped_column(String(80))
    key_custody: Mapped[str | None] = mapped_column(String(120))
    backup_location: Mapped[str | None] = mapped_column(String(60))
    dr_location: Mapped[str | None] = mapped_column(String(60))
    log_destinations: Mapped[list | None] = mapped_column(JSON)
    support_access_path: Mapped[str | None] = mapped_column(String(160))
    support_access_location: Mapped[str | None] = mapped_column(String(60))
    subprocessors: Mapped[list | None] = mapped_column(JSON)  # [{name, location}]
    egress_paths: Mapped[list | None] = mapped_column(JSON)  # [{host, location}]
    status: Mapped[str] = mapped_column(String(10), default="pending")  # COMPONENT_STATUSES
    fail_reasons: Mapped[list | None] = mapped_column(JSON)
    residency_checklist_version: Mapped[str] = mapped_column(String(20), default="v1")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class ReleaseDecision(Base):
    __tablename__ = "release_decisions"

    release_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rel"))
    inventory_version: Mapped[str | None] = mapped_column(String(40), index=True)
    result: Mapped[str] = mapped_column(String(10))  # RELEASE_RESULTS
    reasons: Mapped[list | None] = mapped_column(JSON)  # [{code, component_id, en, ar}]
    next_step: Mapped[dict | None] = mapped_column(JSON)  # {en, ar}
    checks: Mapped[list | None] = mapped_column(JSON)  # [{check, result, reason}]
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(80))


class ResidencyChecklistDoc(Base):
    """Versioned residency checklist document (working definition + instruments). Never claims compliance."""

    __tablename__ = "residency_checklists"

    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    definition: Mapped[dict | None] = mapped_column(JSON)  # {en: [...], ar: [...]}
    instruments: Mapped[list | None] = mapped_column(JSON)  # [{ref, scope, status}]
    check_mode_options: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="provisional")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KeyRecord(Base):
    __tablename__ = "key_records"

    key_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    key_type: Mapped[str] = mapped_column(String(20))  # KEY_TYPES
    version: Mapped[int] = mapped_column(Integer, default=1)
    custody: Mapped[str] = mapped_column(String(120), default="UAE-located and UAE-operated key service")
    rotation_due: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")  # KEY_STATUSES
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime)
    rotation_state: Mapped[dict | None] = mapped_column(JSON)  # {last_audited_step, target_version, started_at, outcome}
    compromise_declared_at: Mapped[datetime | None] = mapped_column(DateTime)
    compromise_deadline_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KeyCompromise(Base):
    """key_compromise_declared {who, when, key_id} (who = pseudonymous actor key)."""

    __tablename__ = "key_compromises"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("kc"))
    key_id: Mapped[str] = mapped_column(String(40), index=True)
    declared_by_key: Mapped[str] = mapped_column(String(80))
    declared_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime)
    rotation_completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EgressAllowListChange(Base):
    """Two-person allow-list change: hash-bound, requester != approver, expires after 5 working days."""

    __tablename__ = "egress_allowlist_changes"

    change_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("egc"))
    proposed_list: Mapped[list | None] = mapped_column(JSON)
    change_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    requester_key: Mapped[str] = mapped_column(String(80))
    approver_1_key: Mapped[str | None] = mapped_column(String(80))
    approver_1_at: Mapped[datetime | None] = mapped_column(DateTime)
    approver_2_key: Mapped[str | None] = mapped_column(String(80))
    approver_2_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # CHANGE_STATUSES
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    supersedes_change_id: Mapped[str | None] = mapped_column(String(40))


class EgressBlockAlert(Base):
    __tablename__ = "egress_block_alerts"

    alert_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ega"))
    host: Mapped[str] = mapped_column(String(255))
    component_ref: Mapped[str | None] = mapped_column(String(80))
    handles_company_data: Mapped[bool] = mapped_column(Boolean, default=True)
    recipient_role: Mapped[str] = mapped_column(String(60), default="qeonix_security_on_call")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ack_due_at: Mapped[datetime] = mapped_column(DateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_by_key: Mapped[str | None] = mapped_column(String(80))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open")  # ALERT_STATUSES
    audit_event_id: Mapped[str | None] = mapped_column(String(40))


class LinkEvent(Base):
    """K12 link activation events (reconstructed into link state at a point in time)."""

    __tablename__ = "k12_link_events"

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lnk"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    onboarding_id: Mapped[str | None] = mapped_column(String(40), index=True)
    link_type: Mapped[str] = mapped_column(String(30))  # LINK_TYPES
    event_type: Mapped[str] = mapped_column(String(20))  # LINK_EVENT_TYPES
    event_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str | None] = mapped_column(String(60))  # bank code, ledger vendor, 'manual_upload', ...
    corrects_link_id: Mapped[str | None] = mapped_column(String(40))  # audited corrected event
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OnboardingCohortRow(Base):
    """One row per onboarding episode (Q362). onboarding_at is never moved; restarts keep the row."""

    __tablename__ = "k12_cohort_rows"

    onboarding_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(40))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    onboarding_at: Mapped[datetime] = mapped_column(DateTime)
    cohort_month: Mapped[str] = mapped_column(String(7))  # YYYY-MM in Asia/Dubai
    cohort_version: Mapped[str] = mapped_column(String(20), default="k12-v1")
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    last_restart_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_all_links_active_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open")  # COHORT_STATUSES
    exit_reason: Mapped[str | None] = mapped_column(String(40))  # opted_out | cancelled
    exited_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
