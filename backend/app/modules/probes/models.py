"""Portal availability probes (E1-S9, K26 path from E1-S4): probe records and the versioned peak-window table."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

CHECK_TYPES = ("sign_in", "dashboard", "documents")
PROBE_RESULTS = ("up", "down", "no_data")
LANGUAGES = ("ar", "en")
WINDOW_TYPES = ("fixed_date", "rule_based", "cohort_derived")
WINDOW_STATUSES = ("active", "retired")


class ProbeRecord(Base):
    __tablename__ = "probe_records"
    __table_args__ = (UniqueConstraint("minute_ts", "check_type", "language", name="uq_probe_minute_check_lang"),)

    probe_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prb"))
    minute_ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, truncated to the minute
    minute_local: Mapped[str | None] = mapped_column(String(25))  # Asia/Dubai value for display
    check_type: Mapped[str] = mapped_column(String(20))  # CHECK_TYPES
    result: Mapped[str] = mapped_column(String(10))  # PROBE_RESULTS
    language: Mapped[str] = mapped_column(String(2))  # LANGUAGES
    latency_ms: Mapped[int | None] = mapped_column(Integer)  # recorded, never a down condition
    reason: Mapped[str | None] = mapped_column(String(60))  # timeout | http_5xx | content_marker | probe_service_down | uaepass_down | dependency_down
    runner: Mapped[str] = mapped_column(String(40), default="uae-runner-1")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PeakWindow(Base):
    """Versioned peak-window instances (Q479). K26 reads the version in force at the measured minute."""

    __tablename__ = "peak_windows"

    window_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pw"))
    window_code: Mapped[str] = mapped_column(String(40), index=True)  # vat_q_deadline | ct_30sep | renewal_cohort | ...
    name_en: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[str] = mapped_column(String(160))
    window_type: Mapped[str] = mapped_column(String(20))  # WINDOW_TYPES
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, start inclusive
    end_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, end exclusive
    start_local: Mapped[str | None] = mapped_column(String(25))
    end_local: Mapped[str | None] = mapped_column(String(25))
    recurrence_rule: Mapped[str | None] = mapped_column(String(160))
    anchor_date: Mapped[date | None] = mapped_column(Date)
    lead_days: Mapped[int | None] = mapped_column(Integer)
    tail_days: Mapped[int | None] = mapped_column(Integer)
    holiday_shift_rule: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    config_version: Mapped[str] = mapped_column(String(20), default="peak-v1")
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    supersedes_window_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="active")  # WINDOW_STATUSES
    placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
