"""KPI catalogue versions, calculation run log (restatements), export log and the synthetic demo fixture.

The dashboard store never holds bank transactions, tax calculations, audit files or document content, and no
company identifiers, licence numbers or trade names (E9-S1 §2.14). The fixture table is synthetic aggregate
input only, labelled 'Demo data', and is never mixed with real company rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

RELEASE_STATES = ("live", "not_yet_available")
REFRESH_PERIODS = ("daily", "monthly")
CELL_STATES = ("shown", "suppressed_fewer_than_N", "merged_other_combined", "not_shown_group_too_small", "complementary_suppressed", "suppressed_dominance")
VALUE_STATES = ("value", "no_data", "not_applicable", "not_yet_available", "blocked", "error")
DATA_SOURCES = ("platform", "demo_fixture")


class KpiDefinition(Base):
    """One row per KPI per catalogue version. Earlier versions stay as history (never edited)."""

    __tablename__ = "kpi_definitions"
    __table_args__ = (UniqueConstraint("kpi_id", "catalogue_version", name="uq_kpi_definition_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("kpd"))
    kpi_id: Mapped[str] = mapped_column(String(8), index=True)
    catalogue_version: Mapped[str] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    name_en: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[str] = mapped_column(String(160))
    definition_en: Mapped[str] = mapped_column(Text)
    definition_ar: Mapped[str] = mapped_column(Text)
    formula_text: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20))
    target_en: Mapped[str | None] = mapped_column(String(255))
    refresh_period: Mapped[str] = mapped_column(String(10))  # REFRESH_PERIODS
    source_list: Mapped[list] = mapped_column(JSON, default=list)
    rule_version_id: Mapped[str] = mapped_column(String(20))
    group: Mapped[str] = mapped_column(String(10))  # live | later
    planned_phase_label: Mapped[str | None] = mapped_column(String(20))
    is_fairness_indicator: Mapped[bool] = mapped_column(Boolean, default=False)
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KpiCalculationRun(Base):
    """kpi_calculation_run log: a new row whenever the inputs (data version) of a KPI-period change.
    A change to a closed period is a restatement and carries a note; closed periods are never silently overwritten."""

    __tablename__ = "kpi_calculation_runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("kpr"))
    kpi_id: Mapped[str] = mapped_column(String(8), index=True)
    period_key: Mapped[str] = mapped_column(String(10), index=True)
    data_source: Mapped[str] = mapped_column(String(20))  # DATA_SOURCES
    rule_version: Mapped[str] = mapped_column(String(40))
    catalogue_version: Mapped[str] = mapped_column(String(20))
    data_version: Mapped[str] = mapped_column(String(20))
    value_hash: Mapped[str] = mapped_column(String(20))
    period_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    restated: Mapped[bool] = mapped_column(Boolean, default=False)
    restatement_note: Mapped[str | None] = mapped_column(String(255))
    supersedes_run_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KpiExport(Base):
    """Every aggregate export (same figures, same suppression as the screen)."""

    __tablename__ = "kpi_exports"

    export_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("kpx"))
    actor_key: Mapped[str] = mapped_column(String(80))
    kpi_ids: Mapped[list] = mapped_column(JSON, default=list)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    dimension: Mapped[str | None] = mapped_column(String(30))
    data_version: Mapped[str] = mapped_column(String(20))
    min_group_size: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KpiFixtureLicence(Base):
    """Synthetic pilot licence used only to demonstrate the dashboard (label 'Demo data').

    No company, licence number or trade name: ``fixture_ref`` is a synthetic reference that never leaves the
    server. Breakdown dimensions are columns; the per-KPI facts (billing lines, flags, renewal, returns,
    deliverables, evaluations, usage) are a JSON document read only by the KPI calculators.
    """

    __tablename__ = "kpi_fixture_licences"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("kfx"))
    fixture_ref: Mapped[str] = mapped_column(String(20), unique=True)
    label: Mapped[str] = mapped_column(String(20), default="Demo data")
    cohort: Mapped[str] = mapped_column(String(40))
    wave: Mapped[str] = mapped_column(String(10))
    enrolment_basis: Mapped[str] = mapped_column(String(30))  # opt_in | default_on_with_opt_out
    licence_category: Mapped[str] = mapped_column(String(40))
    payment_method: Mapped[str | None] = mapped_column(String(40))
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
