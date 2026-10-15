"""Bookkeeping service (E5-S1): intake, classification, review, K14 sampling, K15 review records, K17 timing.

Pure functions over a Session. No HTTP objects. Routing to review is a fixed rule (no confidence scores).
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.time import to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.bookkeeping.models import (
    ChartAccount,
    Classification,
    CompanyRule,
    DataCompleteCheck,
    FxRate,
    PeriodTiming,
    ReviewerLabel,
    ReviewRecord,
    SampleRun,
    Transaction,
    VatCode,
)
from app.modules.config.service import get_config
from app.modules.localmodel.client import get_local_model, language_class

# Category -> (default VAT code, default ledger account). The VAT code is then resolved against the
# versioned vat_code list effective on the transaction date (never a fixed rate).
CATEGORY_DEFAULTS: dict[str, tuple[str, str]] = {
    "sales_revenue": ("SR", "4000"),
    "purchases": ("SR", "5000"),
    "rent": ("SR", "6100"),
    "utilities": ("SR", "6200"),
    "salaries": ("OS", "6300"),
    "government_fees": ("OS", "6400"),
    "bank_charges": ("EX", "6500"),
    "vat_payment": ("OS", "2200"),
    "owner_drawings": ("OS", "3100"),
    "travel": ("SR", "6600"),
}
CATEGORIES = tuple(CATEGORY_DEFAULTS)
REASON_NO_BASIS = "Needs review: no basis found"
REASON_MATCHES = "Matches your earlier choices"
MATERIAL_FIELDS_V1 = ("monetary_amount", "amount", "tax_code", "vat_code", "period", "counterparty", "exception_verdict", "signatory")
MATERIAL_FIELDS_VERSION = "material_fields_v1"
K14_CORRECTED_FIELDS = ("category", "vat_code", "ledger_account", "counterparty")
INCOME_ACCOUNT_PREFIX = "4"


# --- helpers -------------------------------------------------------------------------------------


def role_for(principal: Any, company_id: str) -> str:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else (principal.primary_role() if hasattr(principal, "primary_role") else "none")


def has_function(principal: Any, company_id: str, function: str) -> bool:
    """Owner/remote owner carry every function; a delegate needs the function assigned by the owner."""
    for r in principal.roles_for(company_id):
        fns = r.functions or []
        if r.role in ("owner", "remote_owner") or "all" in fns or function in fns:
            return True
    return False


def require_function(principal: Any, company_id: str, function: str) -> None:
    if not has_function(principal, company_id, function):
        raise Forbidden("You do not have the bookkeeping function for this company. Ask the owner to assign it.", reason_code="NO_FUNCTION", details={"function": function})


def consent_state(db: Session, company_id: str, kind: str = "ledger") -> dict:
    """Consent gate (E4): lazily uses app.modules.consent.service.check_consent; allows when the module is absent.

    ``kind``: 'bank' -> bank_data_open_finance (source bank); 'ledger' -> ledger_invoice_authorisation (source erp,
    covers ERP reads and manual uploads). Any refusal or gate outage is a deny (fail closed).
    """
    consent_type, source = ("bank_data_open_finance", "bank") if kind == "bank" else ("ledger_invoice_authorisation", "erp")
    try:
        from app.modules.consent.service import check_consent  # type: ignore
    except ImportError:
        return {"kind": kind, "allowed": True, "state": "active", "data_from": None, "ended_on": None, "source": "fallback_allow_no_consent_module"}
    try:
        res = check_consent(db, company_id, consent_type, {"source": source, "purpose": "bookkeeping_classification"})
        allowed, reason, consent_id = bool(getattr(res, "allowed", res)), getattr(res, "reason_code", None), getattr(res, "consent_id", None)
    except Exception as exc:  # GateUnavailable or any refusal -> deny
        allowed, reason, consent_id = False, getattr(exc, "reason_code", "GATE_UNAVAILABLE"), None
    ended_on = None
    data_from = None
    state = "active" if allowed else "awaiting_consent"
    try:
        from app.modules.consent.models import Consent  # type: ignore

        latest = db.scalar(select(Consent).where(Consent.company_id == company_id, Consent.consent_type == consent_type).order_by(Consent.granted_at.desc()).limit(1))
        if latest is not None:
            data_from = getattr(latest, "data_from", None)
            if not allowed and latest.status and str(latest.status).startswith("withdrawn"):
                state, ended_on = "withdrawn", (latest.withdrawn_at or latest.expires_at)
            elif not allowed and latest.status == "paused":
                state = "paused"
            elif not allowed and latest.expires_at and latest.expires_at <= utcnow():
                state, ended_on = "expired", latest.expires_at
    except ImportError:  # pragma: no cover
        pass
    return {"kind": kind, "allowed": allowed, "state": state, "reason": reason, "consent_id": consent_id, "data_from": data_from.isoformat() if data_from else None, "ended_on": ended_on.date().isoformat() if ended_on else None}


def period_bounds(period_id: str, fy_end_month: int = 12, fy_end_day: int = 31) -> tuple[date, date]:
    """'2026-Q2' | '2026-04' | 'FY2025' (financial year ending in 2025) | 'YYYY-MM-DD_YYYY-MM-DD'."""
    if "_" in period_id:
        a, b = period_id.split("_", 1)
        return date.fromisoformat(a), date.fromisoformat(b)
    if period_id.upper().startswith("FY"):
        year = int(period_id[2:])
        end = date(year, fy_end_month, fy_end_day)
        start = date(year - 1, fy_end_month, fy_end_day) + timedelta(days=1)
        return start, end
    if "-Q" in period_id.upper():
        year, q = period_id.upper().split("-Q")
        m = (int(q) - 1) * 3 + 1
        start = date(int(year), m, 1)
        end = date(int(year) + (1 if m + 3 > 12 else 0), (m + 3 - 1) % 12 + 1, 1) - timedelta(days=1)
        return start, end
    year, month = period_id.split("-")
    start = date(int(year), int(month), 1)
    end = (date(int(year) + (1 if int(month) == 12 else 0), int(month) % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def dubai_month(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = to_dubai(d).date()
    return f"{d.year:04d}-{d.month:02d}"


def vat_code_for(db: Session, code: str | None, on_date: date) -> VatCode | None:
    """The vat_code row whose effective window covers the tax-point date (none -> no basis)."""
    if not code:
        return None
    return db.scalar(
        select(VatCode).where(VatCode.code == code, VatCode.effective_from <= on_date, (VatCode.effective_to.is_(None)) | (VatCode.effective_to >= on_date)).order_by(VatCode.effective_from.desc())
    )


def vat_codes_effective(db: Session, on_date: date) -> list[VatCode]:
    return list(db.scalars(select(VatCode).where(VatCode.effective_from <= on_date, (VatCode.effective_to.is_(None)) | (VatCode.effective_to >= on_date)).order_by(VatCode.code)))


def chart_effective(db: Session, on_date: date) -> list[ChartAccount]:
    return list(db.scalars(select(ChartAccount).where(ChartAccount.effective_from <= on_date, (ChartAccount.effective_to.is_(None)) | (ChartAccount.effective_to >= on_date)).order_by(ChartAccount.code)))


def fx_rate_for(db: Session, currency: str, on_date: date) -> FxRate | None:
    """Rate on the date, else the last published rate carried over (flagged 'carried'); None when missing."""
    if currency == "AED":
        return None
    exact = db.scalar(select(FxRate).where(FxRate.currency == currency, FxRate.rate_date == on_date))
    if exact:
        return exact
    max_carry = int(get_config(db, "bookkeeping.fx.max_carry_days", 4) or 4)
    prev = db.scalar(select(FxRate).where(FxRate.currency == currency, FxRate.rate_date < on_date, FxRate.rate_date >= on_date - timedelta(days=max_carry)).order_by(FxRate.rate_date.desc()))
    return prev


def convert_to_aed(db: Session, amount_fils: int, currency: str, on_date: date) -> dict:
    if currency == "AED":
        return {"aed_fils": amount_fils, "rate": None, "source": None, "rate_date": None, "carried": False, "missing": False}
    rate = fx_rate_for(db, currency, on_date)
    if rate is None:
        return {"aed_fils": 0, "rate": None, "source": None, "rate_date": None, "carried": False, "missing": True}
    carried = rate.rate_date != on_date or rate.carried
    return {"aed_fils": int(round(amount_fils * rate.rate)), "rate": rate.rate, "source": rate.source, "rate_date": rate.rate_date, "carried": carried, "missing": False}


def _screen_instruction_like(text: str) -> bool:
    try:
        from app.modules.docguard.service import screen_text

        return any(f["flag_type"] in ("A", "C") for f in screen_text(text))
    except ImportError:  # pragma: no cover
        return False


# --- intake --------------------------------------------------------------------------------------


def ingest_transactions(db: Session, company_id: str, rows: list[dict], *, source_kind: str, source_system: str, consent_id: str | None = None, data_from: date | None = None, pull_time: datetime | None = None) -> list[Transaction]:
    """Normalise rows into transactions. Bank rows dated before the consent 'data from' date are not ingested."""
    created: list[Transaction] = []
    pull_time = pull_time or utcnow()

    def _d(v: Any) -> date | None:
        return v if (v is None or isinstance(v, date)) else date.fromisoformat(str(v))

    for row in rows:
        row = {**row, **{k: _d(row.get(k)) for k in ("value_date", "supply_date", "invoice_date")}}
        txn_date = row["txn_date"] if isinstance(row["txn_date"], date) else date.fromisoformat(row["txn_date"])
        if source_kind == "bank" and data_from and txn_date < data_from:
            continue
        source_id = str(row.get("source_id") or row.get("dedupe_key") or hashlib.sha256(f"{txn_date}|{row['description']}|{row['amount_fils']}".encode()).hexdigest()[:24])
        exists = db.scalar(select(Transaction).where(Transaction.company_id == company_id, Transaction.source_system == source_system, Transaction.source_id == source_id))
        if exists:
            continue
        currency = (row.get("currency") or "AED").upper()
        amount = int(row["amount_fils"])
        fx = convert_to_aed(db, abs(amount), currency, txn_date)
        txn = Transaction(
            company_id=company_id,
            source_system=source_system,
            source_id=source_id,
            source_kind=source_kind,
            pull_time=pull_time,
            consent_id=consent_id,
            statement_line_id=row.get("statement_line_id"),
            txn_date=txn_date,
            value_date=row.get("value_date"),
            supply_date=row.get("supply_date"),
            invoice_date=row.get("invoice_date"),
            invoice_number=row.get("invoice_number"),
            description=row["description"],
            description_language=row.get("language_class") or language_class(row["description"]),
            counterparty=row.get("counterparty"),
            direction=row.get("direction") or ("in" if amount >= 0 else "out"),
            original_amount_fils=abs(amount),
            original_currency=currency,
            aed_amount_fils=fx["aed_fils"],
            vat_amount_stated_fils=row.get("vat_amount_stated_fils"),
            fx_rate=fx["rate"],
            fx_rate_source=fx["source"],
            fx_rate_date=fx["rate_date"],
            fx_carried=fx["carried"],
            fx_missing=fx["missing"],
            is_credit_note=bool(row.get("is_credit_note")),
            original_invoice_ref=row.get("original_invoice_ref"),
            special_sector=row.get("special_sector"),
            is_own_transfer=bool(row.get("is_own_transfer")),
            instruction_like_text=_screen_instruction_like(row["description"]),
            manual_unverified=source_kind == "manual",
        )
        db.add(txn)
        created.append(txn)
    db.flush()
    return created


def ingest_from_statement_lines(db: Session, company_id: str, *, consent_id: str | None = None) -> dict:
    """Pull rows from the datalinks module's statement_lines when present; otherwise report the fallback."""
    try:
        from app.modules.datalinks.models import StatementLine  # type: ignore
    except ImportError:
        return {"ingested": 0, "source": "statement_lines_absent_fallback_demo"}
    gate = consent_state(db, company_id, "ledger")
    if not gate["allowed"]:
        return {"ingested": 0, "source": "consent_required", "state": gate["state"]}
    rows = []
    for ln in db.scalars(select(StatementLine).where(StatementLine.company_id == company_id)):
        rows.append({"source_id": ln.dedupe_key or ln.id, "txn_date": ln.txn_date, "description": ln.description, "amount_fils": ln.amount_fils, "currency": ln.currency, "counterparty": ln.counterparty, "statement_line_id": ln.id, "language_class": getattr(ln, "language_class", None)})
    created = ingest_transactions(db, company_id, rows, source_kind="manual", source_system="statement_upload", consent_id=consent_id or gate.get("consent_id"), data_from=gate.get("data_from"))
    return {"ingested": len(created), "source": "statement_lines"}


# --- classification ----------------------------------------------------------------------------


def _prior_choices(db: Session, company_id: str) -> dict[str, str]:
    return {r.counterparty_key: r.category for r in db.scalars(select(CompanyRule).where(CompanyRule.company_id == company_id))}


def classify_transaction(db: Session, txn: Transaction, prior: dict[str, str] | None = None) -> Classification:
    model = get_local_model()
    prior = prior if prior is not None else _prior_choices(db, txn.company_id)
    res = model.classify(txn.description, candidates=list(CATEGORIES), context={"prior_choices": prior, "counterparty": txn.counterparty})
    category = res.output.get("category")
    vat_default, account = CATEGORY_DEFAULTS.get(category, (None, None)) if category else (None, None)
    vat_row = vat_code_for(db, vat_default, txn.txn_date)
    if category and vat_row is None and vat_default:
        category_basis = None  # no VAT code effective on the date: no basis for a posting proposal
    else:
        category_basis = res.rule_id
    if category is None or category_basis is None:
        status, reason = "needs_review", REASON_NO_BASIS
    elif res.rule_id == "prior_choice":
        status, reason = "proposed", REASON_MATCHES
    else:
        status, reason = "proposed", None
    cls = Classification(
        txn_id=txn.id,
        company_id=txn.company_id,
        proposed_category=category,
        proposed_vat_code=vat_row.code if vat_row else None,
        vat_code_version=vat_row.version_id if vat_row else None,
        proposed_ledger_account=account,
        ai_generated=True,
        model_version=res.model_version,
        basis_rule=category_basis,
        status=status,
        review_reason=reason,
        source_date=txn.pull_time,
    )
    db.add(cls)
    db.flush()
    record_event(db, event_type="CLASSIFICATION_PROPOSED", category="agent", company_id=txn.company_id, subject_type="classification", subject_id=cls.id, details={"status": status, "model_version": res.model_version, "basis": category_basis or "none", "language_class": txn.description_language, "treated_as_data": txn.instruction_like_text})
    return cls


def classify_pending(db: Session, company_id: str, *, actor_key: str | None = None, gate: bool = True) -> dict:
    """Classify every unclassified transaction whose source is covered by an active consent (bank or ledger)."""
    gates = {"bank": consent_state(db, company_id, "bank"), "ledger": consent_state(db, company_id, "ledger")} if gate else {"bank": {"allowed": True}, "ledger": {"allowed": True}}
    if gate and not gates["bank"]["allowed"] and not gates["ledger"]["allowed"]:
        raise Forbidden("Waiting for your consent. We read no data from this account until you approve.", reason_code="CONSENT_REQUIRED", details={"bank": gates["bank"]["state"], "ledger": gates["ledger"]["state"]})
    classified_ids = set(db.scalars(select(Classification.txn_id).where(Classification.company_id == company_id)))
    pending = [t for t in db.scalars(select(Transaction).where(Transaction.company_id == company_id, Transaction.source_consent_withdrawn.is_(False)).order_by(Transaction.txn_date, Transaction.id)) if t.id not in classified_ids and gates["bank" if t.source_kind == "bank" else "ledger"]["allowed"]]
    prior = _prior_choices(db, company_id)
    out = {"total": len(pending), "done": 0, "proposed": 0, "needs_review": 0}
    for txn in pending:
        cls = classify_transaction(db, txn, prior)
        out["done"] += 1
        out[cls.status] = out.get(cls.status, 0) + 1
    if actor_key:
        record_event(db, event_type="CLASSIFICATION_RUN", category="agent", actor_key=actor_key, company_id=company_id, details={"total": out["total"], "proposed": out["proposed"], "needs_review": out["needs_review"]})
    return out


# --- review and correction ---------------------------------------------------------------------


def _get(db: Session, company_id: str, classification_id: str) -> tuple[Classification, Transaction]:
    cls = db.get(Classification, classification_id)
    if cls is None or cls.company_id != company_id:
        raise NotFound("transaction not found", reason_code="NOT_FOUND")
    txn = db.get(Transaction, cls.txn_id)
    assert txn is not None
    return cls, txn


def _period_approved(db: Session, company_id: str, on_date: date) -> bool:
    try:
        from app.modules.approvals.service import is_period_approved  # type: ignore
    except ImportError:
        return False
    try:
        return bool(is_period_approved(db, company_id, on_date))
    except Exception:
        return False


def _post(db: Session, cls: Classification) -> None:
    """Posting to the platform ledger (system of record open, Q85): simulated; no-response path kept."""
    if get_config(db, "bookkeeping.ledger.simulate_no_response", False):
        cls.status = "draft_not_posted"
        cls.post_result = "ledger_no_response"
        record_event(db, event_type="POST_FAILED", category="agent", outcome="failed", reason_code="LEDGER_NO_RESPONSE", company_id=cls.company_id, subject_type="classification", subject_id=cls.id)
        return
    cls.status = "posted"
    cls.post_result = "posted"
    cls.posted_at = utcnow()
    record_event(db, event_type="ENTRY_POSTED", category="agent", company_id=cls.company_id, subject_type="classification", subject_id=cls.id, actor_role=cls.reviewer_role, details={"reviewed_at": cls.reviewed_at.isoformat() if cls.reviewed_at else None})


def _snapshot(cls: Classification) -> dict:
    return {k: getattr(cls, k) for k in ("status", "review_reason", "final_category", "final_vat_code", "final_ledger_account", "reviewer_uuid", "reviewer_name", "reviewer_role", "post_result", "made_by_uuid", "made_by_name")} | {"reviewed_at": cls.reviewed_at.isoformat() if cls.reviewed_at else None, "posted_at": cls.posted_at.isoformat() if cls.posted_at else None}


def is_material(changed_fields: list[str]) -> bool:
    return any(f in MATERIAL_FIELDS_V1 for f in changed_fields)


def record_review(db: Session, company_id: str, *, output_type: str, output_id: str, outcome: str, changed_fields: list[str], reviewer_uuid: str | None, reviewer_role: str | None) -> ReviewRecord:
    rec = ReviewRecord(company_id=company_id, output_type=output_type, output_id=output_id, outcome=outcome, changed_fields=changed_fields, material=is_material(changed_fields), material_fields_version=MATERIAL_FIELDS_VERSION, reviewer_uuid=reviewer_uuid, reviewer_role=reviewer_role)
    db.add(rec)
    db.flush()
    return rec


def _label(db: Session, cls: Classification, txn: Transaction, principal: Any, role: str, changed: list[str], reviewer_counterparty: str | None) -> ReviewerLabel:
    lbl = ReviewerLabel(
        company_id=cls.company_id,
        txn_id=txn.id,
        classification_id=cls.id,
        month=dubai_month(txn.txn_date),
        language_class=txn.description_language,
        bank=txn.source_system,
        assigned_category=cls.proposed_category,
        reviewer_category=cls.final_category,
        assigned_vat_code=cls.proposed_vat_code,
        reviewer_vat_code=cls.final_vat_code,
        assigned_account=cls.proposed_ledger_account,
        reviewer_account=cls.final_ledger_account,
        counterparty=reviewer_counterparty or txn.counterparty,
        sample_flag=cls.sample_flag,
        label_source="sampled" if cls.sample_flag else "reviewer_unsampled",
        changed_fields=changed,
        corrected=any(f in K14_CORRECTED_FIELDS for f in changed),
        reviewer_uuid=principal.identity_uuid,
        reviewer_role=role,
        retention_class=txn.retention_class,
    )
    db.add(lbl)
    db.flush()
    return lbl


def _apply_decision(db: Session, cls: Classification, txn: Transaction, principal: Any, company_id: str, *, category: str | None, vat_code: str | None, ledger_account: str | None, counterparty: str | None = None, outcome: str) -> Classification:
    if cls.status == "quarantined":
        raise Conflict("Nothing posted until you decide.", reason_code="QUARANTINED")
    if cls.status in ("posted", "rejected"):
        raise Conflict("this entry is already decided", reason_code="ALREADY_DECIDED")
    role = role_for(principal, company_id)
    if role not in ("owner", "delegate"):
        raise Forbidden("only the owner or a delegate with the bookkeeping function can confirm", reason_code="NO_PERMISSION")
    require_function(principal, company_id, "bookkeeping")
    if vat_code and vat_code_for(db, vat_code, txn.txn_date) is None:
        raise ValidationFailed("this VAT code is not effective on the transaction date", reason_code="VAT_CODE_NOT_EFFECTIVE")
    cls.undo_snapshot = _snapshot(cls)
    cls.undo_session_id = principal.session_id
    cls.final_category = category or cls.proposed_category
    cls.final_vat_code = vat_code or cls.proposed_vat_code
    cls.final_ledger_account = ledger_account or cls.proposed_ledger_account
    if cls.final_category is None or cls.final_vat_code is None:
        raise ValidationFailed("choose a category and a VAT code before posting", reason_code="BASIS_REQUIRED")
    cls.reviewer_uuid, cls.reviewer_name, cls.reviewer_role = principal.identity_uuid, principal.display_name, role
    cls.reviewed_at = utcnow()
    cls.made_by_uuid, cls.made_by_name = principal.identity_uuid, principal.display_name
    cls.version += 1
    cls.updated_at = utcnow()
    changed = [f for f, a, b in (("category", cls.proposed_category, cls.final_category), ("vat_code", cls.proposed_vat_code, cls.final_vat_code), ("ledger_account", cls.proposed_ledger_account, cls.final_ledger_account), ("counterparty", txn.counterparty, counterparty or txn.counterparty)) if a != b]
    if counterparty and counterparty != txn.counterparty:
        txn.counterparty = counterparty
    _label(db, cls, txn, principal, role, changed, counterparty)
    record_review(db, company_id, output_type="classification", output_id=cls.id, outcome="corrected" if changed else "accepted", changed_fields=changed, reviewer_uuid=principal.identity_uuid, reviewer_role=role)
    if txn.counterparty:
        key = txn.counterparty.strip().lower()
        rule = db.scalar(select(CompanyRule).where(CompanyRule.company_id == company_id, CompanyRule.counterparty_key == key))
        if rule is None:
            db.add(CompanyRule(company_id=company_id, counterparty_key=key, category=cls.final_category, vat_code=cls.final_vat_code, ledger_account=cls.final_ledger_account or "", confirmed_by_uuid=principal.identity_uuid))
        else:
            rule.category, rule.vat_code, rule.ledger_account = cls.final_category, cls.final_vat_code, cls.final_ledger_account or ""
    record_event(db, event_type="CLASSIFICATION_CORRECTED" if changed else "CLASSIFICATION_ACCEPTED", category="agent", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="classification", subject_id=cls.id, details={"changed_fields": changed, "label_source": "sampled" if cls.sample_flag else "reviewer_unsampled"})
    _post(db, cls)
    db.flush()
    return cls


def accept(db: Session, company_id: str, classification_id: str, principal: Any) -> Classification:
    cls, txn = _get(db, company_id, classification_id)
    require_function(principal, company_id, "bookkeeping")
    if cls.status == "needs_review" and cls.proposed_category is None:
        raise ValidationFailed("Needs review: no basis found. Choose a category before posting.", reason_code="BASIS_REQUIRED")
    return _apply_decision(db, cls, txn, principal, company_id, category=None, vat_code=None, ledger_account=None, outcome="accepted")


def correct(db: Session, company_id: str, classification_id: str, principal: Any, *, category: str, vat_code: str, ledger_account: str | None = None, counterparty: str | None = None) -> Classification:
    if category not in CATEGORIES:
        raise ValidationFailed("unknown category", reason_code="VALIDATION_FAILED")
    cls, txn = _get(db, company_id, classification_id)
    return _apply_decision(db, cls, txn, principal, company_id, category=category, vat_code=vat_code, ledger_account=ledger_account or CATEGORY_DEFAULTS[category][1], counterparty=counterparty, outcome="corrected")


def reject(db: Session, company_id: str, classification_id: str, principal: Any, reason: str | None = None) -> Classification:
    cls, txn = _get(db, company_id, classification_id)
    if cls.status in ("posted", "quarantined"):
        raise Conflict("this entry cannot be rejected in its current state", reason_code="ALREADY_DECIDED")
    role = role_for(principal, company_id)
    require_function(principal, company_id, "bookkeeping")
    cls.undo_snapshot, cls.undo_session_id = _snapshot(cls), principal.session_id
    cls.status, cls.reviewer_uuid, cls.reviewer_name, cls.reviewer_role, cls.reviewed_at = "rejected", principal.identity_uuid, principal.display_name, role, utcnow()
    cls.made_by_uuid, cls.made_by_name = principal.identity_uuid, principal.display_name
    record_review(db, company_id, output_type="classification", output_id=cls.id, outcome="rejected", changed_fields=[], reviewer_uuid=principal.identity_uuid, reviewer_role=role)
    record_event(db, event_type="CLASSIFICATION_REJECTED", category="agent", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="classification", subject_id=cls.id, details={"reason_code": reason or "none"})
    db.flush()
    return cls


def retry_post(db: Session, company_id: str, classification_id: str, principal: Any) -> Classification:
    cls, _ = _get(db, company_id, classification_id)
    if cls.status != "draft_not_posted":
        raise Conflict("only a 'Draft, not posted' row can be retried", reason_code="NOT_RETRYABLE")
    require_function(principal, company_id, "bookkeeping")
    _post(db, cls)
    db.flush()
    return cls


def undo(db: Session, company_id: str, classification_id: str, principal: Any) -> Classification:
    """Undo the last accept/correct/reject within the same session, before the period is approved."""
    cls, txn = _get(db, company_id, classification_id)
    if not cls.undo_snapshot:
        raise Conflict("nothing to undo", reason_code="NOTHING_TO_UNDO")
    if cls.undo_session_id != principal.session_id:
        raise Conflict("undo is only available within the session that made the change", reason_code="UNDO_WINDOW_CLOSED")
    if _period_approved(db, company_id, txn.txn_date):
        raise Conflict("the period is approved; the entry can no longer be undone", reason_code="PERIOD_APPROVED")
    snap = cls.undo_snapshot
    for k in ("status", "review_reason", "final_category", "final_vat_code", "final_ledger_account", "reviewer_uuid", "reviewer_name", "reviewer_role", "post_result", "made_by_uuid", "made_by_name"):
        setattr(cls, k, snap.get(k))
    cls.reviewed_at = datetime.fromisoformat(snap["reviewed_at"]) if snap.get("reviewed_at") else None
    cls.posted_at = datetime.fromisoformat(snap["posted_at"]) if snap.get("posted_at") else None
    cls.undo_snapshot, cls.undo_session_id = None, None
    cls.version += 1
    # Reversal back to the original value counts as no-change for K14: the label is withdrawn.
    for lbl in db.scalars(select(ReviewerLabel).where(ReviewerLabel.classification_id == cls.id)):
        db.delete(lbl)
    record_event(db, event_type="CLASSIFICATION_UNDO", category="agent", actor_key=principal.actor_key, actor_role=role_for(principal, company_id), company_id=company_id, subject_type="classification", subject_id=cls.id)
    db.flush()
    return cls


def bulk_accept_candidates(db: Session, company_id: str, ids: list[str] | None = None) -> list[tuple[Classification, Transaction]]:
    """Bulk accept is offered only for proposals matching earlier confirmed choices (never quarantined)."""
    stmt = select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == company_id, Classification.status == "proposed", Classification.review_reason == REASON_MATCHES)
    if ids:
        stmt = stmt.where(Classification.id.in_(ids))
    return [(c, t) for c, t in db.execute(stmt).all()]


def bulk_accept_preview(db: Session, company_id: str, ids: list[str] | None = None) -> dict:
    rows = bulk_accept_candidates(db, company_id, ids)
    income = sum(t.aed_amount_fils for c, t in rows if t.direction == "in")
    expenses = sum(t.aed_amount_fils for c, t in rows if t.direction == "out")
    return {"count": len(rows), "total_fils": income + expenses, "income_fils": income, "expenses_fils": expenses, "ids": [c.id for c, _ in rows]}


def bulk_accept(db: Session, company_id: str, principal: Any, ids: list[str] | None = None) -> dict:
    require_function(principal, company_id, "bookkeeping")
    preview = bulk_accept_preview(db, company_id, ids)
    for cid in preview["ids"]:
        accept(db, company_id, cid, principal)
    role = role_for(principal, company_id)
    record_event(db, event_type="BULK_ACCEPT", category="agent", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"count": preview["count"]})
    return preview | {"accepted_by": principal.display_name, "role": role}


# --- quarantine (removed delegate) -------------------------------------------------------------


def quarantine_drafts_for(db: Session, identity_uuid: str, company_id: str, *, removed_on: date | None = None, display_name: str | None = None) -> int:
    """Called by the delegate module when rights are removed: every draft the delegate touched is quarantined."""
    removed_on = removed_on or utcnow().date()
    n = 0
    for cls in db.scalars(select(Classification).where(Classification.company_id == company_id, Classification.made_by_uuid == identity_uuid, Classification.status.in_(("proposed", "needs_review", "draft_not_posted")))):
        cls.status = "quarantined"
        cls.access_removed_on = removed_on
        cls.made_by_name = display_name or cls.made_by_name
        cls.updated_at = utcnow()
        n += 1
        record_event(db, event_type="QUARANTINE_CREATED", category="agent", company_id=company_id, subject_type="classification", subject_id=cls.id, details={"access_removed_on": removed_on.isoformat()})
    try:
        from app.modules.drafts.service import hold_packs_for

        hold_packs_for(db, identity_uuid, company_id, display_name=display_name)
    except ImportError:  # pragma: no cover
        pass
    db.flush()
    return n


def decide_quarantine(db: Session, company_id: str, principal: Any, *, decision: str, reason: str, classification_ids: list[str] | None = None) -> int:
    if role_for(principal, company_id) != "owner":
        raise Forbidden("only the owner decides quarantined drafts", reason_code="NO_PERMISSION")
    if decision not in ("keep_and_review", "discard"):
        raise ValidationFailed("decision must be keep_and_review or discard")
    if not reason or not reason.strip():
        raise ValidationFailed("a reason is required", reason_code="REASON_REQUIRED")
    stmt = select(Classification).where(Classification.company_id == company_id, Classification.status == "quarantined")
    if classification_ids:
        stmt = stmt.where(Classification.id.in_(classification_ids))
    n = 0
    for cls in db.scalars(stmt):
        cls.quarantine_decision, cls.quarantine_decided_by, cls.quarantine_decided_at, cls.quarantine_reason = decision, principal.identity_uuid, utcnow(), reason
        cls.status = "needs_review" if decision == "keep_and_review" else "rejected"
        cls.review_reason = REASON_NO_BASIS if decision == "keep_and_review" else cls.review_reason
        cls.made_by_uuid = None
        cls.updated_at = utcnow()
        n += 1
        record_event(db, event_type="QUARANTINE_DECISION", category="agent", actor_key=principal.actor_key, actor_role="owner", company_id=company_id, subject_type="classification", subject_id=cls.id, details={"decision": decision, "reason_recorded": True})
    db.flush()
    return n


# --- queue / read ------------------------------------------------------------------------------


def to_row(cls: Classification, txn: Transaction, *, lang: str = "en", include_quarantine: bool = True) -> dict:
    """Queue row. Never includes sample_flag or any confidence number (blind review, Q399)."""
    return {
        "id": cls.id,
        "txn_id": txn.id,
        "txn_date": txn.txn_date.isoformat(),
        "description": txn.description,
        "description_language": txn.description_language,
        "counterparty": txn.counterparty,
        "direction": txn.direction,
        "aed_amount_fils": txn.aed_amount_fils,
        "original_amount_fils": txn.original_amount_fils,
        "original_currency": txn.original_currency,
        "fx": {"rate": txn.fx_rate, "source": txn.fx_rate_source, "rate_date": txn.fx_rate_date.isoformat() if txn.fx_rate_date else None, "carried": txn.fx_carried, "missing": txn.fx_missing} if txn.original_currency != "AED" else None,
        "source_kind": txn.source_kind,
        "source_system": txn.source_system,
        "source_id": txn.source_id,
        "source_date": txn.pull_time.isoformat(),
        "consent_id": txn.consent_id,
        "manual_unverified": txn.manual_unverified,
        "treated_as_data": txn.instruction_like_text,
        "consent_withdrawn": txn.source_consent_withdrawn,
        "ai_generated": True,
        "ai_label": "AI-prepared, draft. Please check before posting.",
        "model_version": cls.model_version,
        "status": cls.status,
        "status_label": "Draft, not posted" if cls.status == "draft_not_posted" else cls.status,
        "review_reason": cls.review_reason,
        "proposed": {"category": cls.proposed_category, "vat_code": cls.proposed_vat_code, "vat_code_version": cls.vat_code_version, "ledger_account": cls.proposed_ledger_account},
        "final": {"category": cls.final_category, "vat_code": cls.final_vat_code, "ledger_account": cls.final_ledger_account},
        "reviewer": {"name": cls.reviewer_name, "role": cls.reviewer_role, "at": cls.reviewed_at.isoformat() if cls.reviewed_at else None} if cls.reviewer_uuid else None,
        "posted_at": cls.posted_at.isoformat() if cls.posted_at else None,
        "post_result": cls.post_result,
        "can_undo": bool(cls.undo_snapshot),
        "bulk_eligible": cls.status == "proposed" and cls.review_reason == REASON_MATCHES,
        "quarantine": {"made_by": cls.made_by_name, "access_removed_on": cls.access_removed_on.isoformat() if cls.access_removed_on else None} if (include_quarantine and cls.status == "quarantined") else None,
        "vat_code_label": "configured, pending FTA confirmation",
    }


def list_queue(db: Session, company_id: str, *, status: str | None = None, period: str | None = None, include_quarantined: bool = True) -> list[dict]:
    stmt = select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == company_id)
    if status:
        stmt = stmt.where(Classification.status == status)
    if period:
        start, end = period_bounds(period)
        stmt = stmt.where(Transaction.txn_date >= start, Transaction.txn_date <= end)
    if not include_quarantined:
        stmt = stmt.where(Classification.status != "quarantined")
    rows = db.execute(stmt.order_by(Transaction.txn_date.desc(), Transaction.id)).all()
    return [to_row(c, t) for c, t in rows]


def counts(db: Session, company_id: str) -> dict:
    out = {s: 0 for s in ("proposed", "needs_review", "posted", "rejected", "quarantined", "draft_not_posted")}
    for cls in db.scalars(select(Classification).where(Classification.company_id == company_id)):
        out[cls.status] = out.get(cls.status, 0) + 1
    unclassified = db.scalar(select(Transaction.id).where(Transaction.company_id == company_id).limit(1))
    out["latest_data_at"] = None
    latest = db.scalar(select(Transaction.pull_time).where(Transaction.company_id == company_id).order_by(Transaction.pull_time.desc()).limit(1))
    if latest:
        out["latest_data_at"] = latest.isoformat()
    out["has_transactions"] = unclassified is not None
    return out


def confirmed_transactions(db: Session, company_id: str, start: date, end: date) -> list[tuple[Classification, Transaction]]:
    """Posted (person-confirmed) entries in the window; quarantined rows never count in totals."""
    stmt = select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == company_id, Classification.status == "posted", Transaction.txn_date >= start, Transaction.txn_date <= end, Transaction.source_consent_withdrawn.is_(False))
    return [(c, t) for c, t in db.execute(stmt.order_by(Transaction.txn_date, Transaction.id)).all()]


def excluded_transactions(db: Session, company_id: str, start: date, end: date) -> list[dict]:
    stmt = select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == company_id, Classification.status.in_(("needs_review", "proposed", "draft_not_posted")), Transaction.txn_date >= start, Transaction.txn_date <= end)
    out = []
    for c, t in db.execute(stmt).all():
        reason = "no VAT code" if not (c.final_vat_code or c.proposed_vat_code) else ("unclear category" if c.status == "needs_review" else "not yet confirmed")
        out.append({"classification_id": c.id, "date": t.txn_date.isoformat(), "description": t.description, "aed_amount_fils": t.aed_amount_fils, "reason": reason, "status": c.status})
    return out


def data_hash(db: Session, company_id: str, start: date, end: date) -> str:
    parts = [f"{c.id}|{c.version}|{c.final_category}|{c.final_vat_code}|{t.aed_amount_fils}|{t.txn_date}" for c, t in confirmed_transactions(db, company_id, start, end)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def withdraw_consent(db: Session, company_id: str, consent_id: str | None, *, used_txn_ids: set[str] | None = None) -> dict:
    """K13: flag Class A rows 'source consent withdrawn' (purge on schedule), lock Class B (legal hold)."""
    used_txn_ids = used_txn_ids or set()
    a = b = 0
    stmt = select(Transaction).where(Transaction.company_id == company_id, Transaction.source_kind == "bank")
    if consent_id:
        stmt = stmt.where(Transaction.consent_id == consent_id)
    for txn in db.scalars(stmt):
        txn.source_consent_withdrawn = True
        if txn.id in used_txn_ids:
            txn.retention_class = "B"
            b += 1
        else:
            txn.retention_class = "A"
            a += 1
    record_event(db, event_type="CONSENT_WITHDRAWN_PULLS_STOPPED", category="consent", company_id=company_id, details={"class_a_flagged": a, "class_b_locked": b, "purge_days": get_config(db, "bookkeeping.retention.class_a_purge_days", 30)})
    db.flush()
    return {"class_a_flagged": a, "class_b_locked": b}


# --- K14 sampling (k14-v1) ---------------------------------------------------------------------


def k14_sample_size(population: int, *, min_n: int = 30, pct: float = 0.05, cap: int = 200, too_small: int = 10) -> tuple[int, str]:
    """n = min(N, max(30, ceil(5% x N))), census at N <= 30, 'too small' at N < 10, cap 200."""
    if population < too_small:
        return 0, "too_small"
    if population <= min_n:
        return population, "closed"
    return min(population, max(min_n, math.ceil(pct * population)), cap), "closed"


def k14_seed(company_id: str, month: str, language_class: str, rule_version: str) -> str:
    return hashlib.sha256(f"{company_id}|{month}|{language_class}|{rule_version}".encode()).hexdigest()


def _k14_params(db: Session) -> dict:
    from app.modules.config.service import rule_params

    p = rule_params(db, "k14-v1", {"min_n": 30, "pct": 0.05, "cap": 200, "too_small": 10, "display_threshold": 30, "rolling_months": 3})
    return p


def draw_sample(db: Session, company_id: str, month: str, language_class_: str, *, actor_key: str | None = None) -> SampleRun:
    """Deterministic draw for one stratum; re-running returns the closed run unchanged."""
    rule_version = str(get_config(db, "bookkeeping.sampling_rule_version", "k14-v1"))
    existing = db.scalar(select(SampleRun).where(SampleRun.company_id == company_id, SampleRun.month == month, SampleRun.language_class == language_class_, SampleRun.sampling_rule_version == rule_version))
    if existing:
        return existing
    p = _k14_params(db)
    start, end = period_bounds(month)
    labelled_before = set(db.scalars(select(ReviewerLabel.classification_id).where(ReviewerLabel.company_id == company_id)))
    stmt = select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == company_id, Transaction.txn_date >= start, Transaction.txn_date <= end, Transaction.description_language == language_class_, Transaction.is_own_transfer.is_(False), Transaction.aed_amount_fils != 0, Classification.status != "quarantined")
    population = [c for c, _ in db.execute(stmt).all() if c.id not in labelled_before]
    ids = sorted(c.id for c in population)
    n_count = len(ids)
    n, status = k14_sample_size(n_count, min_n=int(p["min_n"]), pct=float(p["pct"]), cap=int(p["cap"]), too_small=int(p["too_small"]))
    drawn_this_month = sum(r.n for r in db.scalars(select(SampleRun).where(SampleRun.company_id == company_id, SampleRun.month == month)))
    n = max(0, min(n, int(p["cap"]) - drawn_this_month))
    seed = k14_seed(company_id, month, language_class_, rule_version)
    rng = random.Random(seed)
    shuffled = list(ids)
    rng.shuffle(shuffled)
    sample_ids = shuffled[:n]
    run = SampleRun(company_id=company_id, month=month, language_class=language_class_, sampling_rule_version=rule_version, seed=seed, population_count=n_count, sample_ids=sample_ids, n=n, status=status, pooled_platform_level=status == "too_small")
    db.add(run)
    db.flush()
    for c in population:
        if c.id in sample_ids:
            c.sample_flag, c.sample_run_id = True, run.id
    record_event(db, event_type="SAMPLE_RUN_CREATED", category="agent", actor_key=actor_key, company_id=company_id, subject_type="sample_run", subject_id=run.id, details={"month": month, "language_class": language_class_, "N": n_count, "n": n, "status": status, "rule_version": rule_version})
    db.flush()
    return run


def draw_month(db: Session, company_id: str, month: str, *, actor_key: str | None = None) -> list[SampleRun]:
    return [draw_sample(db, company_id, month, lc, actor_key=actor_key) for lc in ("ar", "en", "mixed")]


def _months_back(month: str, k: int) -> list[str]:
    y, m = int(month[:4]), int(month[5:7])
    out = []
    for _ in range(k):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def k14_rate(db: Session, company_id: str, month: str) -> dict:
    """Correction rate on the labelled sample: weighted (N/n) and unweighted, by language class and VAT code.

    Never 'accuracy'; 1 - rate is only the 'agreement rate'. Unsampled corrections are a separate count.
    """
    p = _k14_params(db)
    months = _months_back(month, int(p["rolling_months"]))
    runs = {(r.month, r.language_class): r for r in db.scalars(select(SampleRun).where(SampleRun.company_id == company_id, SampleRun.month.in_(months)))}
    labels = list(db.scalars(select(ReviewerLabel).where(ReviewerLabel.company_id == company_id, ReviewerLabel.month.in_(months))))
    sampled = [lb for lb in labels if lb.sample_flag]
    unsampled_corrections = sum(1 for lb in labels if not lb.sample_flag and lb.corrected)
    by_lang: dict[str, dict] = {}
    by_code: dict[str, dict] = {}
    w_num = w_den = 0.0
    num = den = 0
    for lb in sampled:
        run = runs.get((lb.month, lb.language_class))
        w = (run.population_count / run.n) if run and run.n else 1.0
        den += 1
        num += 1 if lb.corrected else 0
        w_den += w
        w_num += w if lb.corrected else 0
        d = by_lang.setdefault(lb.language_class, {"labelled": 0, "corrected": 0})
        d["labelled"] += 1
        d["corrected"] += 1 if lb.corrected else 0
        c = by_code.setdefault(lb.reviewer_vat_code or "none", {"labelled": 0, "corrected": 0})
        c["labelled"] += 1
        c["corrected"] += 1 if lb.corrected else 0
    measurable = den >= int(p["display_threshold"])
    rate = (num / den) if den else None
    wrate = (w_num / w_den) if w_den else None
    return {
        "label": "Correction rate on a labelled sample",
        "metric": "k14_correction_rate",
        "month": month,
        "rolling_months": months,
        "measurable": measurable,
        "display": None if not measurable else {"weighted_rate": wrate, "unweighted_rate": rate, "agreement_rate": (1 - wrate) if wrate is not None else None},
        "not_measurable_text": None if measurable else f"Not yet measurable: {den} labelled in the rolling 3-month window",
        "labelled_count": den,
        "corrected_count": num,
        "by_language_class": {k: {**v, "unweighted_rate": (v["corrected"] / v["labelled"]) if v["labelled"] else None} for k, v in by_lang.items()},
        "by_vat_code": by_code,
        "module": "bookkeeping",
        "unsampled_correction_count": unsampled_corrections,
        "strata": [{"month": r.month, "language_class": r.language_class, "N": r.population_count, "n": r.n, "status": r.status, "pooled_platform_level": r.pooled_platform_level, "seed": r.seed, "rule_version": r.sampling_rule_version} for r in runs.values()],
        "sampling_rule_version": str(get_config(db, "bookkeeping.sampling_rule_version", "k14-v1")),
    }


# --- K17 completeness and timing (dc-v1) ------------------------------------------------------


DC_V1_DEFAULT = {
    "vat": [
        {"key": "trn", "mandatory": True, "who": "owner", "why": "The TRN identifies the return on EmaraTax", "action": "Add your TRN in settings"},
        {"key": "transactions", "mandatory": True, "who": "owner_or_delegate", "why": "Figures come from the period's transactions", "action": "Upload or link a bank"},
        {"key": "all_reviewed", "mandatory": True, "who": "owner_or_delegate", "why": "Only confirmed transactions count", "action": "Review the queue"},
        {"key": "vat_codes", "mandatory": True, "who": "owner_or_delegate", "why": "Every confirmed line needs a VAT code", "action": "Review the queue"},
        {"key": "fx_rates", "mandatory": True, "who": "owner_or_delegate", "why": "Foreign-currency lines need a rate on the tax-point date", "action": "Add the missing rate"},
        {"key": "ejari", "mandatory": False, "who": "owner", "why": "Ejari supports the premises records", "action": "Add the Ejari contract number"},
    ],
    "ct": [
        {"key": "ct_status", "mandatory": True, "who": "owner", "why": "Tax group, free-zone and unclear statuses are outside the pilot scope", "action": "Confirm the company's corporate-tax status"},
        {"key": "financial_year", "mandatory": True, "who": "owner", "why": "The period follows the financial year", "action": "Confirm the financial year"},
        {"key": "transactions", "mandatory": True, "who": "owner_or_delegate", "why": "Accounting profit comes from the books", "action": "Upload or link a bank"},
        {"key": "all_reviewed", "mandatory": True, "who": "owner_or_delegate", "why": "Only confirmed transactions count", "action": "Review the queue"},
        {"key": "revenue_confirmed", "mandatory": True, "who": "owner", "why": "The Small Business Relief test uses accounting revenue the owner confirms", "action": "Confirm the revenue figure"},
    ],
}


def dc_v1_inputs(db: Session, return_type: str) -> list[dict]:
    cfg = get_config(db, "bookkeeping.dc_v1.inputs", DC_V1_DEFAULT)
    return list((cfg or DC_V1_DEFAULT).get(return_type, []))


def _facts(db: Session, company_id: str, start: date, end: date) -> dict[str, bool]:
    confirmed = confirmed_transactions(db, company_id, start, end)
    excluded = excluded_transactions(db, company_id, start, end)
    return {
        "transactions": bool(confirmed) or bool(excluded),
        "all_reviewed": not excluded,
        "vat_codes": all(c.final_vat_code for c, _ in confirmed),
        "fx_rates": not any(t.fx_missing for _, t in confirmed),
    }


def evaluate_completeness(db: Session, company_id: str, return_type: str, period_id: str, *, facts: dict[str, bool] | None = None, deadline: date | None = None) -> DataCompleteCheck:
    """dc-v1: mandatory inputs per return type. Records the check, starts/supersedes the K17 clock."""
    start, end = period_bounds(period_id)
    f = _facts(db, company_id, start, end) | (facts or {})
    missing = []
    for item in dc_v1_inputs(db, return_type):
        ok = f.get(item["key"], False)
        if not ok:
            missing.append({**item, "status": "Missing", "owner_only": item["who"] == "owner"})
    mandatory_missing = [m for m in missing if m["mandatory"]]
    passed = not mandatory_missing
    blocked = False
    x = get_config(db, "bookkeeping.dc_v1.deadline_minus_days", None)
    if not passed and deadline and x is not None and utcnow().date() >= deadline - timedelta(days=int(x)):
        blocked = True
    check = DataCompleteCheck(company_id=company_id, return_type=return_type, period_id=period_id, version="dc-v1", missing_items=missing, passed=passed, blocked_missing_data=blocked)
    db.add(check)
    current = db.scalar(select(PeriodTiming).where(PeriodTiming.company_id == company_id, PeriodTiming.return_type == return_type, PeriodTiming.period_id == period_id, PeriodTiming.superseded.is_(False)))
    if passed and current is None:
        db.add(PeriodTiming(company_id=company_id, return_type=return_type, period_id=period_id))
        record_event(db, event_type="DATA_COMPLETE_AT", category="agent", company_id=company_id, subject_type="period", subject_id=period_id, details={"return_type": return_type, "version": "dc-v1"})
    elif not passed and current is not None:
        current.superseded = True  # history kept; a new completion starts a new K17 cycle
    record_event(db, event_type="BLOCKED_MISSING_DATA" if blocked else "DATA_COMPLETE_CHECK", category="agent", outcome="blocked" if blocked else ("success" if passed else "incomplete"), company_id=company_id, subject_type="period", subject_id=period_id, details={"return_type": return_type, "missing": [m["key"] for m in missing], "version": "dc-v1"})
    db.flush()
    return check


def mark_draft_ready(db: Session, company_id: str, return_type: str, period_id: str) -> PeriodTiming | None:
    current = db.scalar(select(PeriodTiming).where(PeriodTiming.company_id == company_id, PeriodTiming.return_type == return_type, PeriodTiming.period_id == period_id, PeriodTiming.superseded.is_(False)))
    if current is None:
        return None
    if current.draft_ready_at is None:
        current.draft_ready_at = utcnow()
        record_event(db, event_type="DRAFT_READY_AT", category="agent", company_id=company_id, subject_type="period", subject_id=period_id, details={"return_type": return_type})
    db.flush()
    return current


def timing_card(db: Session, company_id: str, return_type: str, period_id: str) -> dict:
    rows = list(db.scalars(select(PeriodTiming).where(PeriodTiming.company_id == company_id, PeriodTiming.return_type == return_type, PeriodTiming.period_id == period_id).order_by(PeriodTiming.created_at)))
    current = next((r for r in rows if not r.superseded), None)
    last_check = db.scalar(select(DataCompleteCheck).where(DataCompleteCheck.company_id == company_id, DataCompleteCheck.return_type == return_type, DataCompleteCheck.period_id == period_id).order_by(DataCompleteCheck.evaluated_at.desc()).limit(1))
    elapsed = None
    if current and current.draft_ready_at:
        elapsed = int((current.draft_ready_at - current.data_complete_at).total_seconds())
    return {
        "return_type": return_type,
        "period_id": period_id,
        "data_complete_at": current.data_complete_at.isoformat() if current else None,
        "draft_ready_at": current.draft_ready_at.isoformat() if current and current.draft_ready_at else None,
        "elapsed_seconds": elapsed,
        "history": [{"data_complete_at": r.data_complete_at.isoformat(), "draft_ready_at": r.draft_ready_at.isoformat() if r.draft_ready_at else None, "superseded": r.superseded} for r in rows],
        "last_check": {"passed": last_check.passed, "missing_items": last_check.missing_items, "evaluated_at": last_check.evaluated_at.isoformat(), "version": last_check.version, "blocked_missing_data": last_check.blocked_missing_data} if last_check else None,
    }

