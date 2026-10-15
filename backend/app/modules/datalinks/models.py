"""Data-link records: route-holder register, bank configuration and links, pull jobs, manual statement uploads
and parsed statement lines (E4-S3); ERP connector register, links, import runs and mappings (E4-S4); tax
authority link and tax profile (E4-S5); link events and status log (E4-S6)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

ROUTE_HOLDERS = ("licensed_provider_partner", "own_licence", "none")
BANK_AVAILABILITY = ("available", "not_yet_available")
BANK_LINK_STATUSES = ("available", "not_yet_available", "pending", "connecting", "active", "stale", "error", "expired", "consent_withdrawn")
PULL_JOB_STATUSES = ("scheduled", "running", "done", "cancelled", "error")
UPLOAD_STATUSES = ("uploading", "ready", "rejected", "quarantined", "deleted")
UPLOAD_KINDS = ("bank_statement", "erp_export")
ERP_EXPORT_TYPES = ("trial_balance", "general_ledger", "sales_invoices", "purchase_invoices")
ERP_LINK_TYPES = ("connector", "manual upload")
ERP_LINK_STATUSES = ("active", "partial", "error", "needs re-authorisation", "disconnected")
IMPORT_RESULTS = ("success", "partial", "failed")
TAX_LINK_STATUSES = ("not_available", "not_linked", "loading", "active", "error", "format_unrecognised", "consent_withdrawn", "stale", "mismatch", "manual_unverified")
TAX_TYPES = ("vat", "corporate_tax")
TAX_PROFILE_SOURCES = ("company_provided", "document_confirmed", "fta_live")
DUE_DATE_SOURCES = ("derived", "fta_supplied", "user_confirmed", "computed")
SBR_SOURCES = ("unknown", "owner_declared", "fta_confirmed")
LINK_BADGES = ("failed", "consent_expired", "consent_withdrawn", "stale", "status_check_delayed", "partial", "connecting", "not_available_yet", "active")
FRESHNESS_STATES = ("fresh", "late", "stale", "no_consent")
LANGUAGE_CLASSES = ("arabic", "latin", "mixed", "none")


class RouteHolderRegister(Base):
    """Versioned, dated register of who holds the Open Finance route (Q53). Starts at licensed_provider_partner."""

    __tablename__ = "route_holder_register"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    route_holder: Mapped[str] = mapped_column(String(40), default="licensed_provider_partner")
    provider_legal_name: Mapped[str | None] = mapped_column(String(255))
    cbuae_licence_reference: Mapped[str | None] = mapped_column(String(120))
    authorised_activities: Mapped[list | None] = mapped_column(JSON)  # account information service only
    licence_valid_from: Mapped[date | None] = mapped_column(Date)
    licence_valid_to: Mapped[date | None] = mapped_column(Date)
    verification_date: Mapped[date | None] = mapped_column(Date)
    verification_source: Mapped[str | None] = mapped_column(String(255))
    agreement_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    agreement_parties: Mapped[list | None] = mapped_column(JSON)
    agreement_terms_ref: Mapped[str | None] = mapped_column(String(255))  # role, liability, data-use, retention terms
    consent_model: Mapped[dict | None] = mapped_column(JSON)
    processing_location: Mapped[str | None] = mapped_column(String(120))
    processing_operator: Mapped[str | None] = mapped_column(String(255))
    revocation_flow: Mapped[str | None] = mapped_column(String(255))
    coverage_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_review_date: Mapped[date | None] = mapped_column(Date)
    reviewer: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="to_be_confirmed")
    label: Mapped[str | None] = mapped_column(String(255))
    effective_from: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BankConfig(Base):
    __tablename__ = "bank_config"

    bank_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    coverage_status: Mapped[str] = mapped_column(String(30), default="unconfirmed")  # unconfirmed | confirmed | withdrawn
    coverage_confirmation_ref: Mapped[str | None] = mapped_column(String(120))
    coverage_confirmed_date: Mapped[date | None] = mapped_column(Date)
    corporate_account_types_live: Mapped[list | None] = mapped_column(JSON)
    history_window_months: Mapped[int | None] = mapped_column(Integer)  # discovered from provider spec
    k27_overrides: Mapped[dict | None] = mapped_column(JSON)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_me: Mapped[list | None] = mapped_column(JSON)  # identity uuids who asked 'Tell me when available'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BankLink(Base):
    __tablename__ = "bank_links"

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("blk"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    bank_id: Mapped[str] = mapped_column(String(40))
    consent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    consent_version: Mapped[int | None] = mapped_column(Integer)
    external_consent_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="pending")  # BANK_LINK_STATUSES
    accounts: Mapped[list | None] = mapped_column(JSON)  # [{account_ref, masked, holder_name, match_result}]
    last_good_pull_at: Mapped[datetime | None] = mapped_column(DateTime)
    data_as_of: Mapped[date | None] = mapped_column(Date)
    connecting_since: Mapped[datetime | None] = mapped_column(DateTime)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(60))
    correlation_id: Mapped[str | None] = mapped_column(String(40))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    accounts_refreshed: Mapped[int | None] = mapped_column(Integer)
    accounts_total: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PullJob(Base):
    """Scheduled / running consent-checked pull (ingestion orchestrator). Withdrawal cancels them (E4-S2 step 3)."""

    __tablename__ = "pull_jobs"

    job_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    link_id: Mapped[str | None] = mapped_column(String(40))
    consent_id: Mapped[str] = mapped_column(String(40), index=True)
    consent_version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(30), default="bank")
    account_id: Mapped[str | None] = mapped_column(String(80))
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # PULL_JOB_STATUSES
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | on_demand
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(String(40))
    batch_id: Mapped[str | None] = mapped_column(String(40))
    last_blocked_call_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StatementUpload(Base):
    """Manual statement or ERP export upload. Labelled 'manual, unverified'; stays quarantined without its
    notice-and-consent (declaration) record."""

    __tablename__ = "statement_uploads"

    upload_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("upl"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="bank_statement")  # UPLOAD_KINDS
    export_type: Mapped[str | None] = mapped_column(String(30))  # ERP_EXPORT_TYPES for erp_export
    bank_id: Mapped[str | None] = mapped_column(String(40))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    account_ref: Mapped[str | None] = mapped_column(String(80))  # stored, shown masked
    account_masked: Mapped[str | None] = mapped_column(String(20))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))  # csv | xlsx | pdf
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str | None] = mapped_column(String(512))
    uploader_identity_uuid: Mapped[str] = mapped_column(String(64))
    uploader_display_name: Mapped[str | None] = mapped_column(String(255))
    uploader_role: Mapped[str | None] = mapped_column(String(20))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    label: Mapped[str] = mapped_column(String(40), default="manual, unverified")
    malware_scan_result: Mapped[str] = mapped_column(String(30), default="not_scanned")  # clean_stub | infected | not_scanned
    encoding_detected: Mapped[str | None] = mapped_column(String(20))  # UTF-8 | Windows-1256
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rejection_report: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="uploading")  # UPLOAD_STATUSES
    rejection_cause: Mapped[str | None] = mapped_column(String(60))
    quarantine_reason: Mapped[str | None] = mapped_column(String(60))
    # notice-and-consent record (declaration): data submission, not a consent for onward sharing
    declaration_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    purpose: Mapped[str | None] = mapped_column(String(60))
    notice_version: Mapped[str | None] = mapped_column(String(40))
    notice_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    authorisation_consent_id: Mapped[str | None] = mapped_column(String(40))  # ledger/invoice authorisation in force
    batch_id: Mapped[str] = mapped_column(String(40), default=lambda: new_id("bat"))
    data_use_flag: Mapped[str] = mapped_column(String(10), default="active")  # active | stopped
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by_uuid: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class StatementLine(Base):
    """Parsed line from a manual statement upload; readable by the tax/bookkeeping modules. Money in fils."""

    __tablename__ = "statement_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey("statement_uploads.upload_id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    txn_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)  # original text kept
    description_normalised: Mapped[str | None] = mapped_column(Text)  # NFC, bidi controls stripped, Western digits
    amount_fils: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="AED")
    counterparty: Mapped[str | None] = mapped_column(String(255))
    balance_fils: Mapped[int | None] = mapped_column(Integer)
    bank_reference: Mapped[str | None] = mapped_column(String(80))
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    occurrence_index: Mapped[int] = mapped_column(Integer, default=0)
    language_class: Mapped[str] = mapped_column(String(10), default="none")  # LANGUAGE_CLASSES
    label: Mapped[str] = mapped_column(String(40), default="manual, unverified")
    data_use_flag: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ErpConnectorLink(Base):
    __tablename__ = "erp_links"

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("erp"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    system_type: Mapped[str] = mapped_column(String(60))  # from supported-systems config; 'file_export' for uploads
    link_type: Mapped[str] = mapped_column(String(20), default="manual upload")  # ERP_LINK_TYPES
    status: Mapped[str] = mapped_column(String(30), default="active")  # ERP_LINK_STATUSES
    created_by_uuid: Mapped[str | None] = mapped_column(String(64))
    created_by_name: Mapped[str | None] = mapped_column(String(255))
    created_by_role: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)
    data_version: Mapped[int] = mapped_column(Integer, default=0)
    refresh_window_hours: Mapped[int | None] = mapped_column(Integer)  # none for manual
    disconnected_by_uuid: Mapped[str | None] = mapped_column(String(64))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime)
    disconnect_reason: Mapped[str | None] = mapped_column(String(255))
    authorisation_ref: Mapped[str | None] = mapped_column(String(40))  # ledger/invoice authorisation consent id
    secret_ref: Mapped[str | None] = mapped_column(String(40))  # key-custody reference only; never the secret


class ImportRun(Base):
    __tablename__ = "erp_import_runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    link_id: Mapped[str] = mapped_column(ForeignKey("erp_links.link_id"), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    upload_id: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_state: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    record_counts: Mapped[dict | None] = mapped_column(JSON)
    errors: Mapped[list | None] = mapped_column(JSON)
    failed_records: Mapped[list | None] = mapped_column(JSON)  # each with reason; never silently dropped
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    source_record_ids: Mapped[list | None] = mapped_column(JSON)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    result: Mapped[str] = mapped_column(String(20), default="success")  # IMPORT_RESULTS
    validation_findings: Mapped[list | None] = mapped_column(JSON)
    needs_mapping: Mapped[list | None] = mapped_column(JSON)


class ErpMapping(Base):
    __tablename__ = "erp_mappings"

    mapping_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("map"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    system_type: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[dict | None] = mapped_column(JSON)  # account code -> platform account
    needs_mapping: Mapped[list | None] = mapped_column(JSON)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxAuthorityLink(Base):
    __tablename__ = "tax_authority_links"

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tal"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="not_available")  # TAX_LINK_STATUSES
    fixture_key: Mapped[str | None] = mapped_column(String(30))  # demo-only live-read states
    route: Mapped[str | None] = mapped_column(String(40))  # fta_arrangement | named_tax_agent_appointment
    consent_id: Mapped[str | None] = mapped_column(String(40))
    last_good_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_cause: Mapped[str | None] = mapped_column(String(40))  # authority_not_responding | consent_expired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaxProfile(Base):
    """Tax profile keyed by licence x tax type x TRN; versioned; every value carries source and 'as of'."""

    __tablename__ = "tax_profiles"

    profile_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("txp"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    licence_number: Mapped[str | None] = mapped_column(String(40))
    tax_type: Mapped[str] = mapped_column(String(20))  # TAX_TYPES
    trn: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    registration_status: Mapped[str | None] = mapped_column(String(30))  # registered | not_registered | pending | unknown
    filing_status: Mapped[str | None] = mapped_column(String(40))  # as read / as provided; never 'confirmed filed by us'
    filed_date: Mapped[date | None] = mapped_column(Date)
    tax_period_start: Mapped[date | None] = mapped_column(Date)
    tax_period_end: Mapped[date | None] = mapped_column(Date)
    filing_frequency: Mapped[str | None] = mapped_column(String(20))  # monthly | quarterly | annual
    due_dates: Mapped[list | None] = mapped_column(JSON)  # [{period_end, due_date, source}]
    due_date_source: Mapped[str] = mapped_column(String(20), default="computed")  # DUE_DATE_SOURCES
    due_date_override: Mapped[date | None] = mapped_column(Date)
    small_business_relief: Mapped[list | None] = mapped_column(JSON)  # [{period_end, indicator, source}] indicator only
    tax_group_id: Mapped[str | None] = mapped_column(String(40))
    member_relationship: Mapped[str] = mapped_column(String(20), default="unknown")
    source: Mapped[str] = mapped_column(String(20), default="company_provided")  # TAX_PROFILE_SOURCES
    verification_tag: Mapped[str] = mapped_column(String(40), default="unverified")  # verified_by_source | unverified
    entered_by_uuid: Mapped[str | None] = mapped_column(String(64))
    entered_by_name: Mapped[str | None] = mapped_column(String(255))
    entered_by_role: Mapped[str | None] = mapped_column(String(20))
    entered_at: Mapped[datetime | None] = mapped_column(DateTime)
    as_of: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    unknown_fields: Mapped[dict | None] = mapped_column(JSON)
    receipt_upload_ref: Mapped[str | None] = mapped_column(String(40))  # EmaraTax acknowledgement -> 'manual evidence'
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LinkEvent(Base):
    """K12: link activation events (incl. manual_upload fallback flow)."""

    __tablename__ = "link_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    link_type: Mapped[str] = mapped_column(String(30))  # bank | erp | tax_authority | manual_upload
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LinkStatusLog(Base):
    __tablename__ = "link_status_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    cause: Mapped[str | None] = mapped_column(String(80))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
