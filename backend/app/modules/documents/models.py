"""Document store (E7-S5): issued and draft documents, bilingual checks (K28), delivery log, verification lookups,
two-administrator switch requests. Revoked and superseded documents are never deleted."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

DOC_STATUSES = ("draft", "in_review", "signed", "issued", "superseded", "revoked", "withdrawn")
CURRENT_STATUSES = ("draft", "in_review", "signed", "issued")
PUBLIC_STATUSES = ("valid", "superseded", "revoked", "not_valid", "not_found")
SIGNED_STATUS_LAYER = ("signed_valid", "signer_standing_changed", "withdrawn_or_superseded", "invalid")
DELIVERY_EVENTS = ("opened", "downloaded", "exported", "shared")
REVOKE_REASONS = ("issued_in_error", "replaced_by_correction", "signer_instruction", "authority_instruction", "owner_written_request")


class IssuedDocument(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    doc_type: Mapped[str] = mapped_column(String(60), index=True)
    type_class: Mapped[str] = mapped_column(String(10))
    sig_rule_version: Mapped[str] = mapped_column(String(20), default="sig-v1")
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title_en: Mapped[str] = mapped_column(String(255))
    title_ar: Mapped[str] = mapped_column(String(255))
    file_name_en: Mapped[str] = mapped_column(String(255))
    file_name_ar: Mapped[str] = mapped_column(String(255))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    official: Mapped[bool] = mapped_column(Boolean, default=False)  # issued official document vs watermarked draft
    watermark: Mapped[dict | None] = mapped_column(JSON)
    source_record: Mapped[dict] = mapped_column(JSON, default=dict)  # pinned data version, one source for both languages
    fields_en: Mapped[dict] = mapped_column(JSON, default=dict)
    fields_ar: Mapped[dict] = mapped_column(JSON, default=dict)
    data_version: Mapped[str | None] = mapped_column(String(64))
    hash_en: Mapped[str] = mapped_column(String(64))
    hash_ar: Mapped[str] = mapped_column(String(64))
    hash_payload: Mapped[str] = mapped_column(String(64))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    chain_prev: Mapped[str | None] = mapped_column(String(64))
    chain_hash: Mapped[str] = mapped_column(String(64))
    verification_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    precedence_clause_version: Mapped[str | None] = mapped_column(String(20))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    issued_by_uuid: Mapped[str | None] = mapped_column(String(64))
    issued_by_name: Mapped[str] = mapped_column(String(120))
    approval_ref: Mapped[str | None] = mapped_column(String(40))
    supersedes_id: Mapped[str | None] = mapped_column(String(40))
    superseded_by_id: Mapped[str | None] = mapped_column(String(40))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_reason_code: Mapped[str | None] = mapped_column(String(40))
    revoked_note: Mapped[str | None] = mapped_column(Text)
    revoked_by: Mapped[str | None] = mapped_column(String(120))
    revoke_request_ref: Mapped[str | None] = mapped_column(String(80))
    signer_name: Mapped[str | None] = mapped_column(String(120))
    signer_licence: Mapped[str | None] = mapped_column(String(40))
    register_snapshot_id: Mapped[str | None] = mapped_column(String(40))
    signed_status: Mapped[str | None] = mapped_column(String(30))  # SIGNED_STATUS_LAYER (signed outputs only)
    signed_status_source: Mapped[str | None] = mapped_column(String(20))  # signing_firm | authority
    signed_status_ref: Mapped[str | None] = mapped_column(String(80))
    shared_with_uuids: Mapped[list] = mapped_column(JSON, default=list)
    retention_class: Mapped[str] = mapped_column(String(30), default="issued_document")
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BilingualCheck(Base):
    """bilingual-fields-v1 check, run at issue and on each download; stored per check event (K28)."""

    __tablename__ = "document_bilingual_checks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bchk"))
    document_id: Mapped[str | None] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    doc_type: Mapped[str] = mapped_column(String(60))
    event: Mapped[str] = mapped_column(String(10))  # issue | download
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    table_version: Mapped[str] = mapped_column(String(30), default="bilingual-fields-v1")
    fields_checked: Mapped[list] = mapped_column(JSON, default=list)
    fields_mismatched: Mapped[list] = mapped_column(JSON, default=list)
    fields_missing: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    document_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DeliveryLog(Base):
    __tablename__ = "document_delivery_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    event: Mapped[str] = mapped_column(String(12))
    actor_name: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(40))
    lang: Mapped[str | None] = mapped_column(String(5))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VerificationLookup(Base):
    __tablename__ = "document_verification_lookups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_key: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    outcome: Mapped[str] = mapped_column(String(20))


class SwitchRequest(Base):
    """Issue/auditor's-report switch toggle: requested by a Qeonix platform administrator, approved by a second one."""

    __tablename__ = "document_switch_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("swr"))
    key: Mapped[str] = mapped_column(String(80))
    new_state: Mapped[bool] = mapped_column(Boolean)
    old_state: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | applied | refused
