"""Bookkeeping (E5-S1): normalised transactions, AI classification records, reference tables, K14/K15/K17.

Money is in fils. Statuses are strings from the module-level tuples. No confidence scores are stored anywhere:
routing to review is a fixed rule (Q399).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

SOURCE_KINDS = ("bank", "ledger", "einvoice", "manual")
LANGUAGE_CLASSES = ("ar", "en", "mixed")
CLASSIFICATION_STATUSES = ("proposed", "needs_review", "posted", "rejected", "quarantined", "draft_not_posted")
REVIEW_REASONS = ("Needs review: no basis found", "Matches your earlier choices")
LABEL_SOURCES = ("sampled", "reviewer_unsampled")
RETENTION_CLASSES = ("A", "B")
QUARANTINE_DECISIONS = ("keep_and_review", "discard")


class ChartAccount(Base):
    """Versioned chart of accounts (IFRS for SMEs-oriented starter template; product-owned mapping)."""

    __tablename__ = "bk_chart_of_accounts"
    __table_args__ = (UniqueConstraint("code", "version_id", name="uq_bk_coa_code_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("coa"))
    code: Mapped[str] = mapped_column(String(20), index=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(20))  # income | expense | asset | liability | equity
    reporting_line: Mapped[str] = mapped_column(String(80))
    version_id: Mapped[str] = mapped_column(String(20), default="coa-v1")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(120))


class VatCode(Base):
    """Versioned VAT code list mapped to VAT 201 boxes in data (Q86: configured, pending FTA confirmation)."""

    __tablename__ = "bk_vat_codes"
    __table_args__ = (UniqueConstraint("code", "version_id", name="uq_bk_vat_code_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("vc"))
    code: Mapped[str] = mapped_column(String(10), index=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    gloss_en: Mapped[str] = mapped_column(String(255))
    gloss_ar: Mapped[str] = mapped_column(String(255))
    rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    direction: Mapped[str] = mapped_column(String(10), default="both")  # output | input | both
    recoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    return_box_ref: Mapped[str | None] = mapped_column(String(20))
    instrument_ref: Mapped[str | None] = mapped_column(String(255))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    version_id: Mapped[str] = mapped_column(String(20), default="vat-codes-v1")
    status_label: Mapped[str] = mapped_column(String(80), default="configured, pending FTA confirmation")


class FxRate(Base):
    """Dated FX rate (AED per 1 unit of currency); CBUAE default source, carried-over flag (unconfirmed)."""

    __tablename__ = "bk_fx_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date", name="uq_bk_fx_currency_date"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fx"))
    currency: Mapped[str] = mapped_column(String(3), index=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(80), default="CBUAE published rate")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    carried: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_by: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="unconfirmed")


class CompanyRule(Base):
    """A previously confirmed counterparty-to-category mapping ('Matches your earlier choices')."""

    __tablename__ = "bk_company_rules"
    __table_args__ = (UniqueConstraint("company_id", "counterparty_key", name="uq_bk_rule_company_cp"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bkr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    counterparty_key: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    vat_code: Mapped[str] = mapped_column(String(10))
    ledger_account: Mapped[str] = mapped_column(String(20))
    confirmed_by_uuid: Mapped[str | None] = mapped_column(String(64))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Transaction(Base):
    __tablename__ = "bk_transactions"
    __table_args__ = (UniqueConstraint("company_id", "source_system", "source_id", name="uq_bk_txn_source"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("txn"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    source_system: Mapped[str] = mapped_column(String(60))
    source_id: Mapped[str] = mapped_column(String(120))
    source_kind: Mapped[str] = mapped_column(String(20))  # SOURCE_KINDS
    pull_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consent_id: Mapped[str | None] = mapped_column(String(40))
    statement_line_id: Mapped[str | None] = mapped_column(String(40))
    txn_date: Mapped[date] = mapped_column(Date, index=True)  # booking date (payment event)
    value_date: Mapped[date | None] = mapped_column(Date)  # fallback only (vat-tp-v1)
    supply_date: Mapped[date | None] = mapped_column(Date)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_number: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    description_language: Mapped[str] = mapped_column(String(10))  # LANGUAGE_CLASSES
    counterparty: Mapped[str | None] = mapped_column(String(160))
    direction: Mapped[str] = mapped_column(String(5))  # in | out
    original_amount_fils: Mapped[int] = mapped_column(Integer)
    original_currency: Mapped[str] = mapped_column(String(3), default="AED")
    aed_amount_fils: Mapped[int] = mapped_column(Integer)
    vat_amount_stated_fils: Mapped[int | None] = mapped_column(Integer)  # AED VAT stated on invoice
    fx_rate: Mapped[float | None] = mapped_column(Float)
    fx_rate_source: Mapped[str | None] = mapped_column(String(80))
    fx_rate_date: Mapped[date | None] = mapped_column(Date)
    fx_carried: Mapped[bool] = mapped_column(Boolean, default=False)
    fx_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    is_credit_note: Mapped[bool] = mapped_column(Boolean, default=False)
    original_invoice_ref: Mapped[str | None] = mapped_column(String(60))
    special_sector: Mapped[str | None] = mapped_column(String(40))  # real_estate | financial | reverse_charge | import
    is_own_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    instruction_like_text: Mapped[bool] = mapped_column(Boolean, default=False)
    source_consent_withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_class: Mapped[str] = mapped_column(String(1), default="A")
    manual_unverified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Classification(Base):
    __tablename__ = "bk_classifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cls"))
    txn_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    proposed_category: Mapped[str | None] = mapped_column(String(40))
    proposed_vat_code: Mapped[str | None] = mapped_column(String(10))
    proposed_ledger_account: Mapped[str | None] = mapped_column(String(20))
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)  # label cannot be omitted
    model_version: Mapped[str] = mapped_column(String(60))
    basis_rule: Mapped[str | None] = mapped_column(String(60))  # e.g. kw:rent, prior_choice; never a score
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # CLASSIFICATION_STATUSES
    review_reason: Mapped[str | None] = mapped_column(String(80))  # REVIEW_REASONS
    vat_code_version: Mapped[str | None] = mapped_column(String(20))
    final_category: Mapped[str | None] = mapped_column(String(40))
    final_vat_code: Mapped[str | None] = mapped_column(String(10))
    final_ledger_account: Mapped[str | None] = mapped_column(String(20))
    reviewer_uuid: Mapped[str | None] = mapped_column(String(64))
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    reviewer_role: Mapped[str | None] = mapped_column(String(40))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    post_result: Mapped[str | None] = mapped_column(String(40))  # posted | ledger_no_response
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_date: Mapped[datetime | None] = mapped_column(DateTime)  # pull time kept on the posted row
    sample_flag: Mapped[bool] = mapped_column(Boolean, default=False)  # never exposed to reviewers
    sample_run_id: Mapped[str | None] = mapped_column(String(40))
    made_by_uuid: Mapped[str | None] = mapped_column(String(64))
    made_by_name: Mapped[str | None] = mapped_column(String(120))
    access_removed_on: Mapped[date | None] = mapped_column(Date)
    quarantine_decision: Mapped[str | None] = mapped_column(String(20))
    quarantine_decided_by: Mapped[str | None] = mapped_column(String(64))
    quarantine_decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    undo_snapshot: Mapped[dict | None] = mapped_column(JSON)
    undo_session_id: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewerLabel(Base):
    """K14 reviewer label: every accept/correct stores one (language, category, bank, VAT code)."""

    __tablename__ = "bk_k14_labels"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lbl"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    txn_id: Mapped[str] = mapped_column(String(40), index=True)
    classification_id: Mapped[str] = mapped_column(String(40))
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM in Asia/Dubai
    language_class: Mapped[str] = mapped_column(String(10))
    bank: Mapped[str | None] = mapped_column(String(60))
    assigned_category: Mapped[str | None] = mapped_column(String(40))
    reviewer_category: Mapped[str | None] = mapped_column(String(40))
    assigned_vat_code: Mapped[str | None] = mapped_column(String(10))
    reviewer_vat_code: Mapped[str | None] = mapped_column(String(10))
    assigned_account: Mapped[str | None] = mapped_column(String(20))
    reviewer_account: Mapped[str | None] = mapped_column(String(20))
    counterparty: Mapped[str | None] = mapped_column(String(160))
    sample_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    label_source: Mapped[str] = mapped_column(String(20))  # LABEL_SOURCES
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    labelled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewer_uuid: Mapped[str | None] = mapped_column(String(64))
    reviewer_role: Mapped[str | None] = mapped_column(String(40))
    retention_class: Mapped[str] = mapped_column(String(1), default="A")


class SampleRun(Base):
    """k14-v1 sample run: stratum company x month x language_class; closed once drawn."""

    __tablename__ = "bk_k14_sample_runs"
    __table_args__ = (UniqueConstraint("company_id", "month", "language_class", "sampling_rule_version", name="uq_bk_sample_stratum"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("smp"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    month: Mapped[str] = mapped_column(String(7))
    language_class: Mapped[str] = mapped_column(String(10))
    sampling_rule_version: Mapped[str] = mapped_column(String(20))
    seed: Mapped[str] = mapped_column(String(64))
    population_count: Mapped[int] = mapped_column(Integer)
    sample_ids: Mapped[list] = mapped_column(JSON)
    n: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="closed")  # closed | too_small
    pooled_platform_level: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewRecord(Base):
    """K15 review record of an AI output (classification, calculation, draft)."""

    __tablename__ = "bk_k15_review_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rvw"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    output_type: Mapped[str] = mapped_column(String(30))
    output_id: Mapped[str] = mapped_column(String(40), index=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str] = mapped_column(String(30))  # accepted | corrected | rejected | reopened
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    material: Mapped[bool] = mapped_column(Boolean, default=False)
    material_fields_version: Mapped[str] = mapped_column(String(30), default="material_fields_v1")
    reviewer_uuid: Mapped[str | None] = mapped_column(String(64))
    reviewer_role: Mapped[str | None] = mapped_column(String(40))


class DataCompleteCheck(Base):
    """dc-v1 completeness check result (re-evaluated on each data event and at least daily)."""

    __tablename__ = "bk_k17_data_complete_checks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dcc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    return_type: Mapped[str] = mapped_column(String(10))  # vat | ct
    period_id: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(10), default="dc-v1")
    missing_items: Mapped[list] = mapped_column(JSON, default=list)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_missing_data: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PeriodTiming(Base):
    """K17 timing: data_complete_at / draft_ready_at; superseded rows are history and never deleted."""

    __tablename__ = "bk_k17_period_timings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("k17"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    return_type: Mapped[str] = mapped_column(String(10))
    period_id: Mapped[str] = mapped_column(String(40))
    data_complete_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    draft_ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
