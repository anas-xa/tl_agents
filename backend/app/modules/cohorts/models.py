"""Pilot cohort register (E2-S5): per-licence membership, versioned cohorts, two-person change requests.

The register is jointly owned by DET and Qeonix; DET selects, the DET pilot manager approves every change,
Qeonix applies it. Enrolment mode defaults to opt_in until the signed DET-Qeonix agreement exists.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

COHORT_STATUSES = ("draft", "active", "paused", "closed")
ENROLMENT_MODES = ("opt_in", "default_on_with_opt_out")
CHANGE_ACTIONS = ("enrol", "pause", "remove", "close", "wave")
CHANGE_STATES = ("pending", "approved", "applied", "rejected")
MEMBERSHIP_STATUSES = ("enrolled_starts_next_event", "active", "paused", "removed")
NOTICE_EVENT_TYPES = ("enrolled", "paused", "removed", "closed")


class Cohort(Base):
    """One row per cohort version; ``is_current`` marks the version in force. Past versions stay readable."""

    __tablename__ = "cohorts"
    __table_args__ = (UniqueConstraint("cohort_id", "version", name="uq_cohort_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cohort_id: Mapped[str] = mapped_column(String(40), index=True, default=lambda: new_id("coh"))
    code: Mapped[str] = mapped_column(String(40))  # pilot cohort code used in subscription cohort stamps (e.g. PILOT1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[str] = mapped_column(String(255))
    wave: Mapped[str] = mapped_column(String(10))  # label code from config cohort.waves (1a | 1b | 1c)
    phase: Mapped[str] = mapped_column(String(40), default="phase1")
    size_limit: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    modules: Mapped[list | None] = mapped_column(JSON)
    selection_criteria: Mapped[dict | None] = mapped_column(JSON)  # AND between criteria, OR within one
    enrolment_mode: Mapped[str] = mapped_column(String(40), default="opt_in")  # ENROLMENT_MODES
    status: Mapped[str] = mapped_column(String(20), default="draft")  # COHORT_STATUSES
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reason: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class CohortMembership(Base):
    __tablename__ = "cohort_memberships"
    __table_args__ = (UniqueConstraint("cohort_id", "licence_number", name="uq_cohort_licence"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cm"))
    cohort_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="enrolled_starts_next_event")  # MEMBERSHIP_STATUSES
    effective_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)  # UTC stored, Asia/Dubai displayed
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    owner_opted_in_at: Mapped[datetime | None] = mapped_column(DateTime)  # opt_in cohorts: owner's recorded choice
    cohort_version_at_change: Mapped[int | None] = mapped_column(Integer)
    last_notice_event: Mapped[str | None] = mapped_column(String(20))  # NOTICE_EVENT_TYPES
    last_notice_at: Mapped[datetime | None] = mapped_column(DateTime)
    notice_version: Mapped[str | None] = mapped_column(String(20))


class CohortChangeRequest(Base):
    """Two-person change: requester (cohort-management right) and a different approver (cohort.approve)."""

    __tablename__ = "cohort_change_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cc"))
    cohort_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(20))  # CHANGE_ACTIONS
    request_id: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)  # cohort_id + licence + action + request_id
    reason: Mapped[str] = mapped_column(Text)  # audit trail only, never shown to the company
    effective_at: Mapped[datetime] = mapped_column(DateTime)
    allow_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    target_wave: Mapped[str | None] = mapped_column(String(10))
    requester_key: Mapped[str] = mapped_column(String(80))
    approver_key: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(20), default="pending")  # CHANGE_STATES
    rejection_reason: Mapped[str | None] = mapped_column(String(120))
    cohort_version_at_change: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)


class CohortInterest(Base):
    """A company's expression of interest. It only makes the licence a candidate; DET selects."""

    __tablename__ = "cohort_interests"
    __table_args__ = (UniqueConstraint("company_id", "licence_number", name="uq_interest_company_licence"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ci"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    licence_number: Mapped[str] = mapped_column(String(40), index=True)
    registered_by_key: Mapped[str | None] = mapped_column(String(80))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate | selected | declined
    language: Mapped[str | None] = mapped_column(String(5))
