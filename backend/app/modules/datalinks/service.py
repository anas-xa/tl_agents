"""Data links: route readiness and bank links, pull scheduler stub, manual uploads (E4-S3), ERP connector
register (E4-S4), tax authority link and tax profile (E4-S5), link status and freshness (E4-S6)."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.ids import new_id
from app.core.settings import get_settings
from app.core.time import to_dubai, utcnow
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.config.service import get_config, rule_params
from app.modules.datalinks import parsing
from app.modules.datalinks.models import (
    ERP_EXPORT_TYPES,
    SBR_SOURCES,
    TAX_TYPES,
    BankConfig,
    BankLink,
    ErpConnectorLink,
    ErpMapping,
    ImportRun,
    LinkEvent,
    LinkStatusLog,
    PullJob,
    RouteHolderRegister,
    StatementLine,
    StatementUpload,
    TaxAuthorityLink,
    TaxProfile,
)
from app.modules.datalinks.strings import s
from app.modules.licences.models import Licence

UPLOAD_ROOT = Path(get_settings().upload_dir)


# --- rights ----------------------------------------------------------------------------------------------------


def require_function(db: Session, principal: Principal, company_id: str, function: str, *, event: str) -> None:
    """Delegates act only within the functions the owner assigned (uploads, connect accounting data, tax entry)."""
    roles = principal.roles_for(company_id)
    if any(r.role in ("owner", "remote_owner") for r in roles):
        return
    for r in roles:
        if r.role == "delegate":
            fns = r.functions or []
            if "all" in fns or function in fns:
                return
            record_event(db, event_type=event, category="access", outcome="refused", reason_code="DELEGATE_FUNCTION_NOT_ASSIGNED", actor_key=principal.actor_key, actor_role="delegate", company_id=company_id, details={"function": function})
            db.commit()
            raise Forbidden("the owner has not assigned this function to you", reason_code="DELEGATE_FUNCTION_NOT_ASSIGNED", details={"function": function})
    record_event(db, event_type=event, category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"function": function})
    db.commit()
    raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION")


def is_remote_owner_only(principal: Principal, company_id: str) -> bool:
    roles = [r.role for r in principal.roles_for(company_id)]
    return "remote_owner" in roles and "owner" not in roles


# --- route holder and banks (E4-S3) -------------------------------------------------------------------------------


def route_register(db: Session) -> RouteHolderRegister | None:
    return db.scalar(select(RouteHolderRegister).where(RouteHolderRegister.is_current.is_(True)).order_by(RouteHolderRegister.version.desc()))


def route_status(db: Session) -> dict:
    reg = route_register(db)
    route_holder = get_config(db, "datalinks.route_holder", "licensed_provider_partner")
    evidence_complete = bool(reg and reg.provider_legal_name and reg.cbuae_licence_reference and reg.agreement_signed and reg.coverage_confirmed)
    return {
        "route_holder": route_holder,
        "openfinance_enabled": bool(get_config(db, "datalinks.openfinance.enabled", False)),
        "evidence_complete": evidence_complete,
        "coverage_confirmed": bool(reg and reg.coverage_confirmed),
        "agreement_signed": bool(reg and reg.agreement_signed),
        "status": reg.status if reg else "to_be_confirmed",
        "label": reg.label if reg else None,
        "version": reg.version if reg else None,
        "last_review_date": reg.last_review_date.isoformat() if reg and reg.last_review_date else None,
        "bank_link_allowed": route_holder != "none" and evidence_complete and bool(get_config(db, "datalinks.openfinance.enabled", False)),
    }


def bank_availability(db: Session, bank: BankConfig) -> str:
    rs = route_status(db)
    if rs["bank_link_allowed"] and bank.coverage_status == "confirmed":
        return "available"
    return "not_yet_available"


def list_banks(db: Session) -> list[dict]:
    out = []
    for b in db.scalars(select(BankConfig).order_by(BankConfig.demo.desc(), BankConfig.name_en)):
        out.append({"bank_id": b.bank_id, "name_en": b.name_en, "name_ar": b.name_ar, "availability": bank_availability(db, b), "coverage_status": b.coverage_status, "corporate_account_types_live": b.corporate_account_types_live or [], "history_window_months": b.history_window_months, "demo": b.demo, "notify_count": len(b.notify_me or [])})
    return out


def notify_me_when_available(db: Session, principal: Principal, bank_id: str) -> BankConfig:
    bank = db.get(BankConfig, bank_id)
    if bank is None:
        raise NotFound("bank not found", reason_code="BANK_NOT_FOUND")
    ids = list(bank.notify_me or [])
    if principal.identity_uuid not in ids:
        ids.append(principal.identity_uuid)
        bank.notify_me = ids
    record_event(db, event_type="BANK_NOTIFY_ME", category="reminder", actor_key=principal.actor_key, subject_type="bank", subject_id=bank_id)
    return bank


def start_bank_link(db: Session, principal: Principal, company_id: str, bank_id: str, consent_id: str | None) -> BankLink:
    """Phase 2 path, built but refused while the route is not live or the bank is not available (fail closed)."""
    bank = db.get(BankConfig, bank_id)
    if bank is None:
        raise NotFound("bank not found", reason_code="BANK_NOT_FOUND")
    rs = route_status(db)
    if not rs["bank_link_allowed"] or bank_availability(db, bank) != "available":
        record_event(db, event_type="BANK_LINK_REFUSED", category="consent", outcome="refused", reason_code="NO_LICENSED_BANK_ROUTE", actor_key=principal.actor_key, company_id=company_id, subject_type="bank", subject_id=bank_id, details={"route_holder": rs["route_holder"], "evidence_complete": rs["evidence_complete"]})
        db.commit()
        raise SwitchedOff(s("bank.cannot_link_yet", principal.language), reason_code="NO_LICENSED_BANK_ROUTE", details={"bank_id": bank_id, "upload_instead": True})
    link = BankLink(company_id=company_id, bank_id=bank_id, consent_id=consent_id, status="connecting", connecting_since=utcnow(), correlation_id=new_id("cor"))
    db.add(link)
    db.flush()
    _log_status(db, link.link_id, company_id, "bank", None, "connecting", "link_started")
    return link


# --- pull scheduler stub ------------------------------------------------------------------------------------------


def enqueue_scheduled_pulls(db: Session, company_id: str, *, actor_key: str | None = None) -> list[PullJob]:
    """Daily 02:00 Dubai pull scheduler. Switched off until the integration checklist row for the Open Finance
    route is confirmed live; refuses with FEATURE_SWITCHED_OFF."""
    if not get_config(db, "datalinks.openfinance.enabled", False):
        raise SwitchedOff("Open Finance pulls are switched off until the licensed route is confirmed live", reason_code="FEATURE_SWITCHED_OFF", details={"feature": "datalinks.openfinance"})
    from app.modules.consent.service import check_consent

    jobs: list[PullJob] = []
    for link in db.scalars(select(BankLink).where(BankLink.company_id == company_id, BankLink.status.in_(("active", "stale", "error")))):
        for acct in link.accounts or []:
            decision = check_consent(db, company_id, "bank_data_open_finance", {"source": "bank", "data_type": "transactions", "account_id": acct.get("account_ref"), "purpose": "bookkeeping_classification"}, actor_key=actor_key)
            if not decision.allowed:
                continue
            job = PullJob(company_id=company_id, link_id=link.link_id, consent_id=decision.consent_id or "", consent_version=decision.version or 1, account_id=acct.get("account_ref"), scheduled_for=utcnow(), window_end=utcnow().date())
            db.add(job)
            jobs.append(job)
    db.flush()
    return jobs


def run_pull(db: Session, job: PullJob, *, actor_key: str | None = None) -> PullJob:
    """Consent-checked pull: gate before the call and before each page store; the provider adapter is a stub."""
    from app.modules.consent.service import GateUnavailable, check_consent

    job.attempts += 1
    job.status = "running"
    try:
        decision = check_consent(db, job.company_id, "bank_data_open_finance", {"source": job.source, "data_type": "transactions", "account_id": job.account_id}, actor_key=actor_key)
    except GateUnavailable:
        job.status, job.result, job.last_blocked_call_at = "error", "GATE_UNAVAILABLE", utcnow()
        return job
    if not decision.allowed:
        job.status, job.result, job.last_blocked_call_at, job.cancelled_at = "cancelled", decision.reason_code, utcnow(), utcnow()
        job.cancel_reason = "gate_denied"
        return job
    # provider adapter stub: no licensed route in the pilot -> nothing is read
    job.status, job.result, job.record_count = "done", "no_route_stub", 0
    return job


def cancel_pulls_for_consent(db: Session, consent_id: str) -> tuple[int, bool, bool]:
    """Orchestrator hook for withdrawal step 3: cancel queued and running jobs. Returns (cancelled, had_jobs, ok)."""
    jobs = list(db.scalars(select(PullJob).where(PullJob.consent_id == consent_id, PullJob.status.in_(("scheduled", "running")))))
    now = utcnow()
    for j in jobs:
        j.status, j.cancelled_at, j.cancel_reason, j.last_blocked_call_at = "cancelled", now, "consent_withdrawn", now
    for link in db.scalars(select(BankLink).where(BankLink.consent_id == consent_id)):
        _log_status(db, link.link_id, link.company_id, "bank", link.status, "consent_withdrawn", "consent_withdrawn")
        link.status = "consent_withdrawn"
    db.flush()
    return len(jobs), bool(jobs), True


def restrict_lineage_for_consent(db: Session, consent_id: str) -> tuple[int, int]:
    """Withdrawal step 4: data-use flag stopped on every record that carries this consent id; legal holds counted."""
    restricted = on_hold = 0
    for u in db.scalars(select(StatementUpload).where(StatementUpload.authorisation_consent_id == consent_id)):
        u.data_use_flag = "stopped"
        restricted += 1
        if u.legal_hold:
            on_hold += 1
        for line in db.scalars(select(StatementLine).where(StatementLine.upload_id == u.upload_id)):
            line.data_use_flag = "stopped"
    for link in db.scalars(select(ErpConnectorLink).where(ErpConnectorLink.authorisation_ref == consent_id, ErpConnectorLink.status != "disconnected")):
        _log_status(db, link.link_id, link.company_id, "erp", link.status, "disconnected", "consent_withdrawn")
        link.status, link.disconnected_at, link.disconnect_reason = "disconnected", utcnow(), "consent_withdrawn"
    db.flush()
    return restricted, on_hold


# --- manual uploads (E4-S3 / E4-S4 file route) ------------------------------------------------------------------


def _cfg_int(db: Session, key: str, default: int) -> int:
    value = get_config(db, key, None)
    return default if value is None else int(value)


def upload_limits(db: Session) -> dict:
    return {
        "max_size_mb": _cfg_int(db, "datalinks.upload.max_size_mb", 20),
        "max_rows": _cfg_int(db, "datalinks.upload.max_rows", 50000),
        "invalid_row_threshold_percent": _cfg_int(db, "datalinks.upload.invalid_row_threshold_percent", 20),
        "formats": list(get_config(db, "datalinks.upload.formats", ["csv", "xlsx", "pdf"]) or []),
        "statement_age_amber_days": int(get_config(db, "datalinks.upload.statement_age_amber_days", 35) or 35),
        "notice_version": str(get_config(db, "datalinks.upload.notice_version", "v1")),
        "notice_en": s("upload.notice", "en"),
        "notice_ar": s("upload.notice", "ar"),
    }


def _store_file(company_id: str, sha: str, ext: str, data: bytes) -> str:
    folder = UPLOAD_ROOT / company_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    return str(path)


def create_upload(
    db: Session,
    principal: Principal,
    company_id: str,
    *,
    file_name: str,
    data: bytes,
    kind: str = "bank_statement",
    export_type: str | None = None,
    bank_id: str | None = None,
    bank_name: str | None = None,
    account_ref: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    purpose: str | None = None,
    notice_acknowledged: bool = False,
    notice_version: str | None = None,
) -> StatementUpload:
    limits = upload_limits(db)
    safe_name = re.sub(r"[^\w.\- ()؀-ۿ]", "_", Path(file_name or "upload").name)[:200]
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    sha = hashlib.sha256(data).hexdigest()
    upload = StatementUpload(company_id=company_id, kind=kind, export_type=export_type, bank_id=bank_id, bank_name=bank_name, account_ref=account_ref, account_masked=_mask(account_ref), period_start=period_start, period_end=period_end, file_name=safe_name, file_type=ext, file_size=len(data), file_sha256=sha, uploader_identity_uuid=principal.identity_uuid, uploader_display_name=principal.display_name, uploader_role=principal.primary_role(), purpose=purpose, status="uploading")
    db.add(upload)
    db.flush()

    def reject(cause: str, **params) -> StatementUpload:
        upload.status, upload.rejection_cause = "rejected", cause
        upload.rejection_report = [{"line_no": None, "reason": cause, "message_en": s(f"upload.rejected.{cause}", "en", **params), "message_ar": s(f"upload.rejected.{cause}", "ar", **params)}] + list(upload.rejection_report or [])[:100]
        record_event(db, event_type="UPLOAD_REJECTED", category="data_access", outcome="refused", reason_code=cause.upper(), actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="upload", subject_id=upload.upload_id, details={"kind": kind, "file_type": ext, "size": len(data)})
        db.flush()
        return upload

    if ext not in limits["formats"]:
        return reject("wrong_type", limit=limits["max_size_mb"])
    if len(data) > limits["max_size_mb"] * 1024 * 1024:
        return reject("over_size_limit", limit=limits["max_size_mb"])
    if kind == "erp_export" and export_type not in ERP_EXPORT_TYPES:
        raise ValidationFailed("export type must be one of the standard export templates", reason_code="EXPORT_TYPE_INVALID", details={"allowed": list(ERP_EXPORT_TYPES)})
    # malware scan first; infected -> quarantined, audited
    upload.malware_scan_result = parsing.scan_for_malware(data)
    upload.stored_path = _store_file(company_id, sha, ext or "bin", data)
    if upload.malware_scan_result == "infected":
        upload.status, upload.quarantine_reason = "quarantined", "failed_security_check"
        upload.rejection_report = [{"line_no": None, "reason": "failed_security_check", "message_en": s("upload.rejected.failed_security_check", "en"), "message_ar": s("upload.rejected.failed_security_check", "ar")}]
        record_event(db, event_type="UPLOAD_QUARANTINED", category="data_access", outcome="refused", reason_code="FAILED_SECURITY_CHECK", actor_key=principal.actor_key, company_id=company_id, subject_type="upload", subject_id=upload.upload_id)
        db.flush()
        return upload
    # notice-and-consent record: without it the file stays quarantined and nothing is read from it
    from app.modules.consent.service import controlled_lists

    purposes = controlled_lists(db)["purposes"]
    if not notice_acknowledged or not purpose or purpose not in purposes:
        upload.status, upload.quarantine_reason = "quarantined", "no_notice_record"
        upload.rejection_report = [{"line_no": None, "reason": "no_notice_record", "message_en": s("upload.quarantined.no_notice_record", "en"), "message_ar": s("upload.quarantined.no_notice_record", "ar")}]
        record_event(db, event_type="UPLOAD_QUARANTINED", category="data_access", outcome="refused", reason_code="NO_NOTICE_RECORD", actor_key=principal.actor_key, company_id=company_id, subject_type="upload", subject_id=upload.upload_id, details={"purpose_valid": bool(purpose and purpose in purposes)})
        db.flush()
        return upload
    upload.declaration_id = new_id("dcl")
    upload.notice_version = notice_version or limits["notice_version"]
    upload.notice_acknowledged_at = utcnow()
    upload.authorisation_consent_id = _ledger_authorisation_id(db, company_id)
    try:
        rows, encoding = parsing.read_table(ext, data)
        upload.encoding_detected = encoding
        if len(rows) - 1 > limits["max_rows"]:
            return reject("too_many_rows", limit=limits["max_rows"])
        if kind == "erp_export":
            return _finish_erp_export(db, principal, upload, rows)
        accepted, rejected = parsing.parse_rows(rows, account_ref=account_ref)
    except parsing.ParseError as exc:
        return reject(exc.cause)
    total = len(accepted) + len(rejected)
    upload.rows_total = total
    upload.rows_rejected = len(rejected)
    upload.rejection_report = rejected[:500]
    if total == 0 or len(rejected) * 100 > total * limits["invalid_row_threshold_percent"]:
        return reject("too_many_invalid_rows", threshold=limits["invalid_row_threshold_percent"])
    existing = {k for (k,) in db.execute(select(StatementLine.dedupe_key).where(StatementLine.company_id == company_id))}
    skipped = 0
    stored = 0
    for r in accepted:
        if r["dedupe_key"] in existing:
            skipped += 1
            continue
        existing.add(r["dedupe_key"])
        db.add(StatementLine(company_id=company_id, upload_id=upload.upload_id, **r))
        stored += 1
    upload.rows_accepted = stored
    upload.rows_skipped_duplicate = skipped
    if accepted:
        dates = [r["txn_date"] for r in accepted]
        upload.period_start = upload.period_start or min(dates)
        upload.period_end = upload.period_end or max(dates)
    upload.status = "ready"
    db.add(LinkEvent(link_id=upload.upload_id, company_id=company_id, link_type="manual_upload"))
    record_event(db, event_type="UPLOAD_STORED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="upload", subject_id=upload.upload_id, details={"kind": kind, "file_type": ext, "rows_total": total, "rows_accepted": stored, "rows_rejected": len(rejected), "rows_skipped_duplicate": skipped, "encoding": encoding, "label": upload.label, "declaration_id": upload.declaration_id, "notice_version": upload.notice_version})
    db.flush()
    return upload


def _ledger_authorisation_id(db: Session, company_id: str) -> str | None:
    try:
        from app.modules.consent.models import Consent

        c = db.scalar(select(Consent).where(Consent.company_id == company_id, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active").order_by(Consent.version.desc()))
        return c.consent_id if c else None
    except Exception:  # pragma: no cover
        return None


def _finish_erp_export(db: Session, principal: Principal, upload: StatementUpload, rows: list[list[str]]) -> StatementUpload:
    """ERP export (trial balance, GL, invoice listings): validated and counted; records needing mapping listed;
    nothing silently dropped. Rows themselves are kept in the stored file (Phase 1 file route)."""
    header = [parsing.normalise_text(h).lower() for h in rows[0]]
    body = rows[1:]
    failed: list[dict] = []
    findings: list[dict] = []
    needs_mapping: set[str] = set()
    mapping = db.scalar(select(ErpMapping).where(ErpMapping.company_id == upload.company_id, ErpMapping.is_current.is_(True)))
    known = set((mapping.rules or {}).keys()) if mapping else set()
    debit_total = credit_total = 0
    acct_idx = next((i for i, h in enumerate(header) if h in ("account", "account code", "code", "رمز الحساب", "الحساب")), None)
    debit_idx = next((i for i, h in enumerate(header) if h in ("debit", "dr", "مدين")), None)
    credit_idx = next((i for i, h in enumerate(header) if h in ("credit", "cr", "دائن")), None)
    amount_idx = next((i for i, h in enumerate(header) if h in ("amount", "total", "المبلغ", "الإجمالي")), None)
    if acct_idx is None and amount_idx is None and debit_idx is None:
        upload.status, upload.rejection_cause = "rejected", "unknown_header"
        upload.rejection_report = [{"line_no": None, "reason": "unknown_header", "message_en": s("upload.rejected.unknown_header", "en"), "message_ar": s("upload.rejected.unknown_header", "ar")}]
        db.flush()
        return upload
    for n, row in enumerate(body, start=2):
        code = parsing.normalise_text(row[acct_idx]) if acct_idx is not None and acct_idx < len(row) else ""
        d = parsing.parse_amount(row[debit_idx]) if debit_idx is not None and debit_idx < len(row) else None
        c = parsing.parse_amount(row[credit_idx]) if credit_idx is not None and credit_idx < len(row) else None
        a = parsing.parse_amount(row[amount_idx]) if amount_idx is not None and amount_idx < len(row) else None
        if d is None and c is None and a is None:
            failed.append({"line_no": n, "reason": "amount_invalid"})
            continue
        debit_total += d or 0
        credit_total += c or 0
        if code and code not in known:
            needs_mapping.add(code)
    if upload.export_type == "trial_balance" and (debit_idx is not None and credit_idx is not None):
        tolerance = get_config(db, "datalinks.erp.debits_equal_credits_tolerance_fils", None)
        diff = abs(debit_total - credit_total)
        findings.append({"check": "debits_equal_credits", "difference_fils": diff, "tolerance_fils": tolerance, "status": "open_q63" if tolerance is None else ("ok" if diff <= int(tolerance) else "failed")})
    upload.rows_total = len(body)
    upload.rows_rejected = len(failed)
    upload.rows_accepted = len(body) - len(failed)
    upload.rejection_report = failed[:500]
    threshold = int(get_config(db, "datalinks.upload.invalid_row_threshold_percent", 20) or 20)
    if not body or len(failed) * 100 > len(body) * threshold:
        upload.status, upload.rejection_cause = "rejected", "too_many_invalid_rows"
        db.flush()
        return upload
    link = db.scalar(select(ErpConnectorLink).where(ErpConnectorLink.company_id == upload.company_id, ErpConnectorLink.link_type == "manual upload", ErpConnectorLink.status != "disconnected"))
    if link is None:
        link = ErpConnectorLink(company_id=upload.company_id, system_type="file_export", link_type="manual upload", status="active", created_by_uuid=principal.identity_uuid, created_by_name=principal.display_name, created_by_role=principal.primary_role(), authorisation_ref=upload.authorisation_consent_id)
        db.add(link)
        db.flush()
        db.add(LinkEvent(link_id=link.link_id, company_id=upload.company_id, link_type="manual_upload"))
        _log_status(db, link.link_id, upload.company_id, "erp", None, "active", "file_export_uploaded")
    link.data_version += 1
    link.last_refreshed_at = utcnow()
    link.status = "partial" if failed or needs_mapping else "active"
    run = ImportRun(link_id=link.link_id, company_id=upload.company_id, upload_id=upload.upload_id, ended_at=utcnow(), period_start=upload.period_start, period_end=upload.period_end, record_counts={upload.export_type or "records": upload.rows_accepted}, failed_records=failed[:500], data_version=link.data_version, trigger="manual", result="partial" if failed or needs_mapping else "success", validation_findings=findings, needs_mapping=sorted(needs_mapping)[:200])
    db.add(run)
    upload.status = "ready"
    record_event(db, event_type="ERP_IMPORT_RUN", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=upload.company_id, subject_type="erp_import_run", subject_id=run.run_id, details={"export_type": upload.export_type, "rows_accepted": upload.rows_accepted, "rows_failed": len(failed), "needs_mapping": len(needs_mapping), "data_version": link.data_version, "result": run.result})
    db.flush()
    return upload



def _mask(value: str | None) -> str | None:
    if not value:
        return None
    tail = "".join(ch for ch in str(value) if ch.isalnum())[-4:]
    return f"•••• {tail}"


def list_uploads(db: Session, company_id: str, *, include_deleted: bool = False) -> list[StatementUpload]:
    stmt = select(StatementUpload).where(StatementUpload.company_id == company_id).order_by(StatementUpload.uploaded_at.desc())
    if not include_deleted:
        stmt = stmt.where(StatementUpload.status != "deleted")
    return list(db.scalars(stmt))


def get_upload(db: Session, company_id: str, upload_id: str) -> StatementUpload:
    u = db.get(StatementUpload, upload_id)
    if u is None or u.company_id != company_id:
        raise NotFound("upload not found", reason_code="UPLOAD_NOT_FOUND")
    return u


def delete_upload(db: Session, principal: Principal, upload: StatementUpload) -> StatementUpload:
    if upload.legal_hold:
        raise Conflict("this batch is under a legal hold; it is locked, not removed", reason_code="LEGAL_HOLD")
    upload.status, upload.deleted_at, upload.deleted_by_uuid, upload.data_use_flag = "deleted", utcnow(), principal.identity_uuid, "stopped"
    n = 0
    for line in db.scalars(select(StatementLine).where(StatementLine.upload_id == upload.upload_id)):
        line.data_use_flag = "stopped"
        db.delete(line)
        n += 1
    record_event(db, event_type="UPLOAD_BATCH_DELETED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=upload.company_id, subject_type="upload", subject_id=upload.upload_id, details={"batch_id": upload.batch_id, "lines_removed": n, "file_retained_under_retention_rule": True})
    return upload


def serialize_upload(db: Session, u: StatementUpload, lang: str = "en") -> dict:
    amber = int(get_config(db, "datalinks.upload.statement_age_amber_days", 35) or 35)
    age_days = (utcnow().date() - u.period_end).days if u.period_end else None
    return {
        "upload_id": u.upload_id,
        "kind": u.kind,
        "export_type": u.export_type,
        "bank_id": u.bank_id,
        "bank_name": u.bank_name,
        "account_masked": u.account_masked,
        "period_start": u.period_start.isoformat() if u.period_start else None,
        "period_end": u.period_end.isoformat() if u.period_end else None,
        "file_name": u.file_name,
        "file_type": u.file_type,
        "file_size": u.file_size,
        "uploaded_by": u.uploader_display_name,
        "uploader_role": u.uploader_role,
        "uploaded_at": u.uploaded_at.isoformat(),
        "label": u.label,
        "malware_scan_result": u.malware_scan_result,
        "encoding_detected": u.encoding_detected,
        "rows_total": u.rows_total,
        "rows_accepted": u.rows_accepted,
        "rows_rejected": u.rows_rejected,
        "rows_skipped_duplicate": u.rows_skipped_duplicate,
        "rejection_report": (u.rejection_report or [])[:50],
        "status": u.status,
        "rejection_cause": u.rejection_cause,
        "quarantine_reason": u.quarantine_reason,
        "declaration_id": u.declaration_id,
        "purpose": u.purpose,
        "notice_version": u.notice_version,
        "notice_acknowledged_at": u.notice_acknowledged_at.isoformat() if u.notice_acknowledged_at else None,
        "authorisation_consent_id": u.authorisation_consent_id,
        "batch_id": u.batch_id,
        "data_use_flag": u.data_use_flag,
        "legal_hold": u.legal_hold,
        "is_demo": u.is_demo,
        "statement_age_days": age_days,
        "statement_age_badge": None if age_days is None else ("update_due" if age_days >= amber else "neutral"),
        "data_as_of": u.period_end.isoformat() if u.period_end else None,
    }


def statement_lines(db: Session, company_id: str, *, upload_id: str | None = None, limit: int = 500) -> list[dict]:
    stmt = select(StatementLine).where(StatementLine.company_id == company_id, StatementLine.data_use_flag == "active").order_by(StatementLine.txn_date, StatementLine.id)
    if upload_id:
        stmt = stmt.where(StatementLine.upload_id == upload_id)
    return [
        {"id": r.id, "upload_id": r.upload_id, "line_no": r.line_no, "txn_date": r.txn_date.isoformat(), "description": r.description, "amount_fils": r.amount_fils, "currency": r.currency, "counterparty": r.counterparty, "balance_fils": r.balance_fils, "language_class": r.language_class, "label": r.label}
        for r in db.scalars(stmt.limit(limit))
    ]


def manual_data_age(db: Session, company_id: str) -> dict:
    latest = db.scalar(select(func.max(StatementUpload.period_end)).where(StatementUpload.company_id == company_id, StatementUpload.status == "ready", StatementUpload.kind == "bank_statement"))
    latest_upload = db.scalar(select(func.max(StatementUpload.uploaded_at)).where(StatementUpload.company_id == company_id, StatementUpload.status == "ready"))
    amber = int(get_config(db, "datalinks.upload.statement_age_amber_days", 35) or 35)
    reminder = int(get_config(db, "datalinks.links.manual_upload_reminder_days", 35) or 35)
    age = (utcnow().date() - latest).days if latest else None
    upload_age = (utcnow() - latest_upload).days if latest_upload else None
    return {"latest_statement_end": latest.isoformat() if latest else None, "latest_upload_at": latest_upload.isoformat() if latest_upload else None, "manual_data_age_days": age, "upload_age_days": upload_age, "badge": None if age is None else ("update_due" if age >= amber else "neutral"), "amber_days": amber, "reminder_due": upload_age is not None and upload_age >= reminder}


# --- ERP connector register (E4-S4) -------------------------------------------------------------------------


def erp_register(db: Session) -> dict:
    return {
        "supported_systems": list(get_config(db, "datalinks.erp.supported_systems", []) or []),
        "vendor_flags": dict(get_config(db, "datalinks.erp.vendor_flags", {}) or {}),
        "file_upload_enabled": bool(get_config(db, "datalinks.erp.file_upload_enabled", True)),
        "accepted_export_types": list(ERP_EXPORT_TYPES),
        "preconditions": list(get_config(db, "datalinks.erp.vendor_preconditions", []) or []),
        "remote_owner_can_connect": False,
        "open_items": get_config(db, "datalinks.erp.open_items_q63", {}),
    }


def connect_erp(db: Session, principal: Principal, company_id: str, system_type: str) -> ErpConnectorLink:
    reg = erp_register(db)
    if system_type not in reg["supported_systems"]:
        record_event(db, event_type="ERP_CONNECT_REFUSED", category="access", outcome="refused", reason_code="CONNECTOR_NOT_AVAILABLE", actor_key=principal.actor_key, company_id=company_id, details={"system_type": system_type})
        db.commit()
        raise SwitchedOff(s("erp.not_available", principal.language), reason_code="CONNECTOR_NOT_AVAILABLE", details={"system_type": system_type, "supported_systems": reg["supported_systems"]})
    if not reg["vendor_flags"].get(system_type, False):
        raise SwitchedOff("this connector is switched off for production data until DET and DESC confirm", reason_code="FEATURE_SWITCHED_OFF", details={"system_type": system_type})
    if db.scalar(select(ErpConnectorLink).where(ErpConnectorLink.company_id == company_id, ErpConnectorLink.link_type == "connector", ErpConnectorLink.status != "disconnected")):
        raise Conflict("one connector link per company", reason_code="ONE_LINK_PER_COMPANY")
    auth = _ledger_authorisation_id(db, company_id)
    if not auth:
        raise Forbidden("the company has not given the ledger and invoice data authorisation", reason_code="NO_LEDGER_AUTHORISATION")
    link = ErpConnectorLink(company_id=company_id, system_type=system_type, link_type="connector", status="active", created_by_uuid=principal.identity_uuid, created_by_name=principal.display_name, created_by_role=principal.primary_role(), authorisation_ref=auth, secret_ref=new_id("kms"))
    db.add(link)
    db.flush()
    db.add(LinkEvent(link_id=link.link_id, company_id=company_id, link_type="erp"))
    return link


def disconnect_erp(db: Session, principal: Principal, company_id: str, link_id: str, reason: str | None) -> ErpConnectorLink:
    link = db.get(ErpConnectorLink, link_id)
    if link is None or link.company_id != company_id:
        raise NotFound("link not found", reason_code="LINK_NOT_FOUND")
    _log_status(db, link.link_id, company_id, "erp", link.status, "disconnected", "disconnected_by_user")
    link.status, link.disconnected_at, link.disconnected_by_uuid, link.disconnect_reason, link.secret_ref = "disconnected", utcnow(), principal.identity_uuid, reason, None
    record_event(db, event_type="ERP_DISCONNECTED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="erp_link", subject_id=link_id, details={"link_type": link.link_type, "secret_revoked": True})
    return link


def serialize_erp_link(db: Session, link: ErpConnectorLink) -> dict:
    runs = list(db.scalars(select(ImportRun).where(ImportRun.link_id == link.link_id).order_by(ImportRun.started_at.desc()).limit(10)))
    chip = {"active": "connected", "partial": "needs_attention", "error": "needs_attention", "needs re-authorisation": "needs_attention", "disconnected": "disconnected"}[link.status]
    return {
        "link_id": link.link_id,
        "system_type": link.system_type,
        "link_type": link.link_type,
        "status": link.status,
        "chip": chip,
        "created_by": link.created_by_name,
        "created_by_role": link.created_by_role,
        "created_at": link.created_at.isoformat(),
        "last_refreshed_at": link.last_refreshed_at.isoformat() if link.last_refreshed_at else None,
        "data_version": link.data_version,
        "refresh_window_hours": link.refresh_window_hours,
        "disconnected_at": link.disconnected_at.isoformat() if link.disconnected_at else None,
        "disconnect_reason": link.disconnect_reason,
        "authorisation_ref": link.authorisation_ref,
        "runs": [{"run_id": r.run_id, "started_at": r.started_at.isoformat(), "result": r.result, "record_counts": r.record_counts, "failed_count": len(r.failed_records or []), "needs_mapping": r.needs_mapping or [], "validation_findings": r.validation_findings or [], "data_version": r.data_version, "period_state": r.period_state} for r in runs],
    }


# --- tax authority link and tax profile (E4-S5) ----------------------------------------------------------------


def tax_link(db: Session, company_id: str) -> TaxAuthorityLink:
    link = db.scalar(select(TaxAuthorityLink).where(TaxAuthorityLink.company_id == company_id))
    if link is None:
        link = TaxAuthorityLink(company_id=company_id, status="not_available")
        db.add(link)
        db.flush()
    return link


def tax_link_state(db: Session, company_id: str, principal: Principal | None = None) -> dict:
    link = tax_link(db, company_id)
    switch_on = bool(get_config(db, "datalinks.tax.adapter.enabled", False))
    profiles = current_tax_profiles(db, company_id)
    status = link.status
    if link.fixture_key:  # demo-only live-read states, labelled 'Demo data'
        status = {"withdrawn": "consent_withdrawn"}.get(link.fixture_key, link.fixture_key)
    elif not switch_on:
        status = "manual_unverified" if profiles else "not_available"
    elif status == "not_available":
        status = "not_linked"
    stale_days = int(get_config(db, "datalinks.tax.stale_threshold_days", 7) or 7)
    if switch_on and status == "active" and link.last_good_read_at and (utcnow() - link.last_good_read_at).days > stale_days:
        status = "stale"
    remote = bool(principal and is_remote_owner_only(principal, company_id))
    return {
        "link_id": link.link_id,
        "status": status,
        "switch_on": switch_on,
        "fixture_key": link.fixture_key,
        "demo_data": link.fixture_key is not None,
        "route": link.route,
        "consent_id": link.consent_id,
        "last_good_read_at": link.last_good_read_at.isoformat() if link.last_good_read_at else None,
        "error_cause": link.error_cause,
        "stale_threshold_days": stale_days,
        "poll_boost_before_due": get_config(db, "datalinks.tax.poll_boost_before_due", None),
        "remote_owner_consent_online": False if remote else None,
        "remote_owner_status_text": s("tax.remote_owner_status", "en") if remote else None,
        "credential_policy": "The platform never holds EmaraTax credentials; company-credentials route forbidden.",
        "profiles": [serialize_tax_profile(p) for p in profiles],
    }


def current_tax_profiles(db: Session, company_id: str) -> list[TaxProfile]:
    return list(db.scalars(select(TaxProfile).where(TaxProfile.company_id == company_id, TaxProfile.is_current.is_(True)).order_by(TaxProfile.tax_type)))


def compute_due_dates(db: Session, tax_type: str, period_end: date | None, frequency: str | None) -> list[dict]:
    """Due dates by the rule register (CT 9 months after period end; VAT 28 days after period end) [REG]."""
    if period_end is None:
        return []
    if tax_type == "corporate_tax":
        p = rule_params(db, "ct-due-v1", {"months_after_period_end": 9})
        months = int(p.get("months_after_period_end", 9))
        y, m = period_end.year, period_end.month + months
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        due = date(y, m, min(period_end.day, 28))
        return [{"period_end": period_end.isoformat(), "due_date": due.isoformat(), "source": "computed", "rule": "ct-due-v1"}]
    p = rule_params(db, "vat-due-v1", {"days_after_period_end": 28})
    days = int(p.get("days_after_period_end", 28))
    out = []
    step = 1 if frequency == "monthly" else 3
    pe = period_end
    for _ in range(4):
        out.append({"period_end": pe.isoformat(), "due_date": (pe + timedelta(days=days)).isoformat(), "source": "computed", "rule": "vat-due-v1"})
        y, m = pe.year, pe.month + step
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        pe = date(y, m, calendar.monthrange(y, m)[1])
    return out


def set_tax_profile(db: Session, principal: Principal, company_id: str, payload: dict) -> TaxProfile:
    tax_type = payload.get("tax_type")
    if tax_type not in TAX_TYPES:
        raise ValidationFailed("tax type must be vat or corporate_tax", reason_code="TAX_TYPE_INVALID")
    trn = parsing.normalise_text(payload.get("trn") or "") or None
    pattern = get_config(db, "datalinks.tax.trn_pattern", r"^\d{15}$")
    if trn and not re.fullmatch(str(pattern), trn):
        raise ValidationFailed("TRN format not recognised (validation rule provisional, Q390 open)", reason_code="TRN_INVALID")
    frequencies = list(get_config(db, "datalinks.tax.filing_frequencies", ["monthly", "quarterly", "annual"]) or [])
    freq = payload.get("filing_frequency")
    if freq and freq not in frequencies:
        raise ValidationFailed("filing frequency not in the value list (open Q390)", reason_code="FREQUENCY_INVALID", details={"allowed": frequencies})
    ps, pe = _d(payload.get("tax_period_start")), _d(payload.get("tax_period_end"))
    if ps and pe and pe < ps:
        raise ValidationFailed("period end is before period start", reason_code="PERIOD_INVALID")
    source = payload.get("source") or "company_provided"
    if source not in ("company_provided", "document_confirmed"):
        raise ValidationFailed("manual entry source must be company_provided or document_confirmed", reason_code="SOURCE_INVALID")
    if source == "document_confirmed" and not payload.get("receipt_upload_ref"):
        raise ValidationFailed("document_confirmed needs an uploaded EmaraTax acknowledgement reference", reason_code="RECEIPT_REQUIRED")
    sbr = []
    for item in payload.get("small_business_relief") or []:
        src = item.get("source", "unknown")
        if src not in SBR_SOURCES:
            raise ValidationFailed("relief source must be unknown, owner_declared or fta_confirmed", reason_code="SBR_SOURCE_INVALID")
        if src == "fta_confirmed":
            raise ValidationFailed("relief can be marked fta_confirmed only by the authority feed", reason_code="SBR_SOURCE_INVALID")
        sbr.append({"period_end": item.get("period_end"), "indicator": item.get("indicator", "unknown"), "source": src, "note": "indicator only; relief rules live in the rule register"})
    licence = db.scalar(select(Licence).where(Licence.company_id == company_id))
    # duplicate TRN across companies (same tax type) is held for review, never silently accepted
    if trn:
        dup = db.scalar(select(TaxProfile).where(TaxProfile.trn == trn, TaxProfile.tax_type == tax_type, TaxProfile.company_id != company_id, TaxProfile.is_current.is_(True)))
        if dup is not None:
            raise Conflict("this TRN is already recorded for another company; held for review", reason_code="TRN_DUPLICATE")
    previous = db.scalar(select(TaxProfile).where(TaxProfile.company_id == company_id, TaxProfile.tax_type == tax_type, TaxProfile.is_current.is_(True)))
    if previous is not None:
        if previous.source == "fta_live":
            raise Conflict("values read from the authority cannot be overwritten by hand; raise a mismatch instead", reason_code="AUTHORITY_VALUE_PROTECTED")
        previous.is_current = False
    due_source = "user_confirmed" if payload.get("due_date_confirmed") else "computed"
    due_dates = compute_due_dates(db, tax_type, pe, freq)
    if payload.get("due_date_override"):
        due_dates = [{"period_end": pe.isoformat() if pe else None, "due_date": _d(payload["due_date_override"]).isoformat(), "source": "user_confirmed"}] + due_dates
        due_source = "user_confirmed"
    profile = TaxProfile(
        company_id=company_id,
        licence_number=licence.licence_number if licence else None,
        tax_type=tax_type,
        trn=trn,
        version=(previous.version + 1) if previous else 1,
        registration_status=payload.get("registration_status") or "unknown",
        filing_status=payload.get("filing_status"),
        filed_date=_d(payload.get("filed_date")),
        tax_period_start=ps,
        tax_period_end=pe,
        filing_frequency=freq,
        due_dates=due_dates,
        due_date_source=due_source,
        due_date_override=_d(payload.get("due_date_override")),
        small_business_relief=sbr,
        tax_group_id=payload.get("tax_group_id"),
        member_relationship=payload.get("member_relationship") or "unknown",
        source=source,
        verification_tag="unverified",
        entered_by_uuid=principal.identity_uuid,
        entered_by_name=principal.display_name,
        entered_by_role=principal.primary_role(),
        entered_at=utcnow(),
        as_of=utcnow(),
        data_version=(previous.data_version + 1) if previous else 1,
        unknown_fields={k: v for k, v in payload.items() if k not in _KNOWN_PROFILE_FIELDS} or None,
        receipt_upload_ref=payload.get("receipt_upload_ref"),
    )
    db.add(profile)
    db.flush()
    record_event(db, event_type="TAX_PROFILE_ENTERED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="tax_profile", subject_id=profile.profile_id, details={"tax_type": tax_type, "source": source, "verification_tag": "unverified", "version": profile.version, "due_date_source": due_source, "has_receipt": bool(profile.receipt_upload_ref)})
    return profile


_KNOWN_PROFILE_FIELDS = {"tax_type", "trn", "registration_status", "filing_status", "filed_date", "tax_period_start", "tax_period_end", "filing_frequency", "due_date_confirmed", "due_date_override", "small_business_relief", "tax_group_id", "member_relationship", "source", "receipt_upload_ref"}


def _d(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValidationFailed("date must be YYYY-MM-DD", reason_code="DATE_INVALID") from exc


def serialize_tax_profile(p: TaxProfile) -> dict:
    source_label = {"company_provided": "Entered by hand", "document_confirmed": "Entered by hand (manual evidence)", "fta_live": "From the tax authority"}[p.source]
    return {
        "profile_id": p.profile_id,
        "licence_number": p.licence_number,
        "tax_type": p.tax_type,
        "trn": p.trn,
        "version": p.version,
        "registration_status": p.registration_status,
        "filing_status": p.filing_status,
        "filing_status_basis": "as read from the authority" if p.source == "fta_live" else "as provided by the company",
        "filed_date": p.filed_date.isoformat() if p.filed_date else None,
        "filed_date_available": p.filed_date is not None,
        "tax_period_start": p.tax_period_start.isoformat() if p.tax_period_start else None,
        "tax_period_end": p.tax_period_end.isoformat() if p.tax_period_end else None,
        "filing_frequency": p.filing_frequency,
        "due_dates": p.due_dates or [],
        "due_date_source": p.due_date_source,
        "small_business_relief": p.small_business_relief or [],
        "tax_group_id": p.tax_group_id,
        "member_relationship": p.member_relationship,
        "source": p.source,
        "source_label": source_label,
        "verification_tag": p.verification_tag,
        "not_confirmed_by_authority": p.source != "fta_live",
        "k7k8_measurable": p.source == "fta_live" or (p.source == "document_confirmed" and p.filed_date is not None),
        "entered_by": p.entered_by_name,
        "entered_by_role": p.entered_by_role,
        "entered_at": p.entered_at.isoformat() if p.entered_at else None,
        "as_of": p.as_of.isoformat(),
        "as_of_dubai": to_dubai(p.as_of).isoformat(),
        "data_version": p.data_version,
        "unknown_fields": p.unknown_fields,
        "receipt_upload_ref": p.receipt_upload_ref,
        "is_demo": p.is_demo,
    }


# --- link status and freshness (E4-S6) -----------------------------------------------------------------------


def k27_windows(db: Session) -> dict:
    default = {"bank": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 48}, "det": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72}, "fta": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72}, "erp": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72}, "e_invoice": {"expected_interval_h": 1, "tolerance_h": 1, "stale_after_h": 24}}
    params = rule_params(db, "k27-windows-v1", {"windows": default})
    return dict(params.get("windows", default))


def freshness_state(last_refresh_at: datetime | None, window: dict, *, now: datetime | None = None, consent_ok: bool = True) -> dict:
    """fresh (<= expected + tolerance) | late (<= stale_after) | stale (> stale_after) | no_consent. Plain elapsed time (Q78)."""
    now = now or utcnow()
    if not consent_ok:
        return {"state": "no_consent", "age_hours": None, "reason": "consent"}
    if last_refresh_at is None:
        return {"state": "stale", "age_hours": None, "reason": "never_refreshed"}
    age_h = (now - last_refresh_at).total_seconds() / 3600
    fresh_limit = float(window.get("expected_interval_h", 24)) + float(window.get("tolerance_h", 0))
    stale_after = float(window.get("stale_after_h", 48))
    if age_h <= fresh_limit:
        state = "fresh"
    elif age_h <= stale_after:
        state = "late"
    else:
        state = "stale"
    return {"state": state, "age_hours": round(age_h, 1), "reason": None if state == "fresh" else "window"}


BADGE_ORDER = ["failed", "consent_expired", "consent_withdrawn", "stale", "status_check_delayed", "partial", "connecting", "not_available_yet", "active"]


def resolve_badge(*, link_status: str, consent_status: str | None, freshness: str, connecting_since: datetime | None, last_check_at: datetime | None, accounts_refreshed: int | None, accounts_total: int | None, now: datetime | None = None, delayed_after_h: float = 6.0) -> str:
    """Nine badges, worst first. Withdrawn/expired consent always overrides a technical 'active'."""
    now = now or utcnow()
    if consent_status in ("withdrawn_on_platform", "revocation_confirmed_by_provider") or link_status == "consent_withdrawn":
        return "consent_withdrawn"
    if consent_status == "expired" or link_status == "expired":
        return "consent_expired"
    if link_status in ("error",):
        return "failed"
    if link_status in ("not_yet_available", "available", "not_available", "not_linked", "manual_unverified"):
        return "not_available_yet"
    if link_status in ("connecting", "pending"):
        return "connecting"
    if freshness == "stale":
        return "stale"
    if last_check_at is not None and (now - last_check_at).total_seconds() / 3600 > delayed_after_h:
        return "status_check_delayed"
    if accounts_total and accounts_refreshed is not None and accounts_refreshed < accounts_total:
        return "partial"
    return "active"


def link_rows(db: Session, company_id: str, *, lang: str = "en", now: datetime | None = None) -> dict:
    now = now or utcnow()
    windows = k27_windows(db)
    connecting_timeout = int(get_config(db, "datalinks.links.connecting_timeout_minutes", 15) or 15)
    rows: list[dict] = []
    consents_by_id: dict[str, object] = {}
    try:
        from app.modules.consent.models import Consent

        consents = list(db.scalars(select(Consent).where(Consent.company_id == company_id)))
        consents_by_id = {c.consent_id: c for c in consents}
    except Exception:  # pragma: no cover
        consents = []
    # bank links (Phase 2 objects; demo rows only in the pilot)
    for link in db.scalars(select(BankLink).where(BankLink.company_id == company_id)):
        bank = db.get(BankConfig, link.bank_id)
        consent = consents_by_id.get(link.consent_id or "")
        cstatus = getattr(consent, "status", None)
        consent_ok = cstatus == "active"
        fr = freshness_state(link.last_good_pull_at, {**windows.get("bank", {}), **((bank.k27_overrides or {}) if bank else {})}, now=now, consent_ok=consent_ok)
        badge = resolve_badge(link_status=link.status, consent_status=cstatus, freshness=fr["state"], connecting_since=link.connecting_since, last_check_at=link.last_check_at, accounts_refreshed=link.accounts_refreshed, accounts_total=link.accounts_total, now=now)
        still_connecting = badge == "connecting" and link.connecting_since is not None and (now - link.connecting_since) > timedelta(minutes=connecting_timeout)
        missing = [a.get("masked") for a in (link.accounts or [])[link.accounts_refreshed or 0 :]] if badge == "partial" else []
        rows.append(_row("bank", (bank.name_ar if lang == "ar" else bank.name_en) if bank else link.bank_id, link.link_id, badge, link.last_good_pull_at, windows.get("bank", {}), fr, next_step=_next_step(badge, "bank"), reason_line=_reason(badge, link, consent), reference_id=link.correlation_id if badge == "failed" else None, masked_account=(link.accounts or [{}])[0].get("masked") if link.accounts else None, connecting_since=link.connecting_since, still_connecting=still_connecting, partial={"refreshed": link.accounts_refreshed, "total": link.accounts_total, "missing": missing} if badge == "partial" else None, last_known={"status": link.status, "at": link.last_check_at.isoformat() if link.last_check_at else None} if badge == "status_check_delayed" else None, is_demo=link.is_demo, data_as_of=link.data_as_of.isoformat() if link.data_as_of else None))
    if not any(r["source_type"] == "bank" for r in rows):
        rs = route_status(db)
        pending_bank = next((c for c in consents if c.consent_type == "bank_data_open_finance" and c.status == "pending"), None)
        rows.append(_row("bank", (pending_bank.provider_name if pending_bank else None) or ("البنك" if lang == "ar" else "Bank"), "bank-route", "connecting" if pending_bank else "not_available_yet", None, windows.get("bank", {}), {"state": "no_consent" if not pending_bank else "stale", "age_hours": None, "reason": "route_not_live"}, next_step="upload_files", reason_line="bank_route_not_live" if not rs["bank_link_allowed"] else None, excluded_from_k27=True, masked_account=_mask(pending_bank.account_ids[0]) if pending_bank and pending_bank.account_ids else None, connecting_since=pending_bank.granted_at if pending_bank else None, still_connecting=bool(pending_bank and (now - pending_bank.granted_at) > timedelta(minutes=connecting_timeout))))
    # ERP links
    erp_links = list(db.scalars(select(ErpConnectorLink).where(ErpConnectorLink.company_id == company_id)))
    for link in erp_links:
        consent = consents_by_id.get(link.authorisation_ref or "")
        cstatus = getattr(consent, "status", None)
        if link.link_type == "manual upload":
            continue  # reported on the uploaded-data line
        fr = freshness_state(link.last_refreshed_at, windows.get("erp", {}), now=now, consent_ok=cstatus == "active")
        lstatus = {"needs re-authorisation": "error", "disconnected": "consent_withdrawn" if link.disconnect_reason == "consent_withdrawn" else "not_yet_available"}.get(link.status, link.status)
        badge = resolve_badge(link_status=lstatus, consent_status=cstatus, freshness=fr["state"], connecting_since=None, last_check_at=None, accounts_refreshed=None, accounts_total=None, now=now)
        rows.append(_row("erp", link.system_type, link.link_id, badge, link.last_refreshed_at, windows.get("erp", {}), fr, next_step=_next_step(badge, "erp"), reason_line=None))
    if not any(r["source_type"] == "erp" for r in rows):
        rows.append(_row("erp", "Accounting system" if lang == "en" else "النظام المحاسبي", "erp-route", "not_available_yet", None, windows.get("erp", {}), {"state": "no_consent", "age_hours": None, "reason": "no_connector_in_pilot"}, next_step="upload_files", excluded_from_k27=True))
    # tax authority
    tl = tax_link_state(db, company_id)
    tax_badge = {"error": "failed", "consent_withdrawn": "consent_withdrawn", "stale": "stale", "loading": "connecting", "active": "active", "mismatch": "partial", "format_unrecognised": "failed"}.get(tl["status"], "not_available_yet")
    tfr = freshness_state(tax_link(db, company_id).last_good_read_at, windows.get("fta", {}), now=now, consent_ok=tl["status"] in ("active", "stale", "mismatch"))
    rows.append(_row("tax_authority", "FTA (EmaraTax)" if lang == "en" else "الهيئة الاتحادية للضرائب", tl["link_id"], tax_badge, tax_link(db, company_id).last_good_read_at, windows.get("fta", {}), tfr, next_step="enter_manually" if tax_badge == "not_available_yet" else _next_step(tax_badge, "tax_authority"), reason_line=tl.get("error_cause"), excluded_from_k27=not tl["switch_on"], is_demo=tl["demo_data"], manual_entries=[{"tax_type": p["tax_type"], "entered_at": p["entered_at"], "source": p["source"]} for p in tl["profiles"]]))
    # DET licensing (nightly reconciliation; read from the licence record)
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    dfr = freshness_state(lic.last_det_refresh_at if lic else None, windows.get("det", {}), now=now)
    rows.append(_row("det", "DET licensing" if lang == "en" else "تراخيص دائرة الاقتصاد والسياحة", f"det-{company_id}", "stale" if dfr["state"] == "stale" else "active", lic.last_det_refresh_at if lic else None, windows.get("det", {}), dfr, next_step=None))
    # e-invoicing provider: inactive before the mandate dates; excluded from K27
    rows.append(_row("e_invoice_provider", "E-invoicing provider" if lang == "en" else "مزوّد الفوترة الإلكترونية", "einv-route", "not_available_yet", None, windows.get("e_invoice", {}), {"state": "no_consent", "age_hours": None, "reason": "inactive_before_mandate"}, next_step=None, excluded_from_k27=True))
    rows.sort(key=lambda r: (BADGE_ORDER.index(r["badge"]), r["last_successful_refresh_at"] or ""))
    manual = manual_data_age(db, company_id)
    uploads = [u for u in list_uploads(db, company_id) if u.status == "ready"]
    manual_line = {"source_type": "manual_upload", "label": "manual, unverified", "count": len(uploads), **manual, "state": ("stale" if manual["badge"] == "update_due" else "fresh") if manual["latest_statement_end"] else "none", "note": "late upload = stale with a prompt, never an error (Q78)"}
    automated = [r for r in rows if not r.get("excluded_from_k27")]
    fresh = [r for r in automated if r["freshness"]["state"] == "fresh"]
    k27 = {"connector_line": {"numerator": len(fresh), "denominator": len(automated), "share": round(len(fresh) / len(automated), 3) if automated else None}, "uploaded_line": {"numerator": 1 if manual_line["state"] == "fresh" else 0, "denominator": 1 if manual_line["state"] != "none" else 0}, "excluded_counts": {"not_available": sum(1 for r in rows if r["badge"] == "not_available_yet"), "consent_withdrawn": sum(1 for r in rows if r["badge"] == "consent_withdrawn"), "consent_expired": sum(1 for r in rows if r["badge"] == "consent_expired")}, "window_calendar_mode": get_config(db, "datalinks.k27.window_calendar_mode", "plain_elapsed"), "snapshot_at": now.isoformat(), "windows": windows, "open_items": "Q403: inclusion of connecting/partial/error, snapshot time zone, zero-source display"}
    needs_attention = [r["link_id"] for r in rows if r["badge"] in ("failed", "consent_expired", "consent_withdrawn", "stale", "status_check_delayed", "partial")]
    return {"rows": rows, "manual_uploads_line": manual_line, "k27": k27, "needs_attention": needs_attention, "connecting_timeout_minutes": connecting_timeout, "holiday_note": None}


def _row(source_type: str, source_name: str, link_id: str, badge: str, last: datetime | None, window: dict, fr: dict, *, next_step: str | None, reason_line: str | None = None, reference_id: str | None = None, masked_account: str | None = None, connecting_since: datetime | None = None, still_connecting: bool = False, partial: dict | None = None, last_known: dict | None = None, excluded_from_k27: bool = False, is_demo: bool = False, data_as_of: str | None = None, manual_entries: list | None = None) -> dict:
    return {"source_type": source_type, "source_name": source_name, "link_id": link_id, "badge": badge, "last_successful_refresh_at": last.isoformat() if last else None, "last_successful_refresh_dubai": to_dubai(last).isoformat() if last else None, "expected_refresh_window": window, "freshness": fr, "data_age_days": round(fr["age_hours"] / 24, 1) if fr.get("age_hours") is not None else None, "next_step": next_step, "reason_line": reason_line, "reference_id": reference_id, "masked_account": masked_account, "connecting_since": connecting_since.isoformat() if connecting_since else None, "still_connecting": still_connecting, "partial": partial, "last_known": last_known, "excluded_from_k27": excluded_from_k27, "is_demo": is_demo, "data_as_of": data_as_of, "manual_entries": manual_entries or []}


def _next_step(badge: str, source_type: str) -> str | None:
    return {"failed": "reconnect", "consent_expired": "renew_consent", "consent_withdrawn": "open_consent_centre", "stale": "upload_files" if source_type != "tax_authority" else "read_again", "status_check_delayed": None, "partial": "see_accounts", "connecting": None, "not_available_yet": "upload_files" if source_type != "tax_authority" else "enter_manually", "active": None}.get(badge)


def _reason(badge: str, link: BankLink, consent) -> str | None:
    if badge == "failed":
        return link.error_code or "bank_did_not_respond"
    if badge == "consent_withdrawn":
        return "no_data_is_being_read"
    if badge == "consent_expired":
        return getattr(consent, "expires_at", None).isoformat() if getattr(consent, "expires_at", None) else "consent_expired"
    return None


def _log_status(db: Session, link_id: str, company_id: str, source_type: str, old: str | None, new: str, cause: str) -> None:
    if old == new:
        return
    db.add(LinkStatusLog(link_id=link_id, company_id=company_id, source_type=source_type, old_status=old, new_status=new, cause=cause))
    record_event(db, event_type="LINK_STATUS_CHANGED", category="system", company_id=company_id, subject_type="link", subject_id=link_id, details={"source_type": source_type, "old": old, "new": new, "cause": cause})


def technical_detail(db: Session, principal: Principal, company_id: str, link_id: str) -> dict:
    """Staff-only detail: codes, timestamps, correlation id, attempts; never account numbers, balances or tokens."""
    link = db.get(BankLink, link_id)
    record_event(db, event_type="LINK_TECHNICAL_DETAIL_OPENED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="link", subject_id=link_id)
    if link is None:
        logs = list(db.scalars(select(LinkStatusLog).where(LinkStatusLog.link_id == link_id).order_by(LinkStatusLog.changed_at.desc()).limit(20)))
        return {"link_id": link_id, "status_log": [{"old": lg.old_status, "new": lg.new_status, "cause": lg.cause, "at": lg.changed_at.isoformat()} for lg in logs]}
    return {"link_id": link_id, "error_code": link.error_code, "provider": link.bank_id, "timestamp": link.updated_at.isoformat(), "correlation_id": link.correlation_id, "attempt_count": link.attempt_count, "next_retry_at": link.next_retry_at.isoformat() if link.next_retry_at else None, "raw_payload_included": False, "note": "Q404 open: raw payload inclusion"}
