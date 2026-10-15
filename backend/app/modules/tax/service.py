"""Tax calculation service (E5-S2): versioned rule lookup, VAT (vat-tp-v1), corporate tax, SBR indicator,
scope block, escalation triggers 1-5, staleness. Preparation only; nothing is ever sent anywhere.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.ids import reference_code
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as bk
from app.modules.companies.models import Company
from app.modules.config.models import RuleRegisterEntry
from app.modules.config.service import get_config
from app.modules.tax.models import (
    DRAFT_LABEL,
    ESCALATED_STATUS,
    SCOPE_BLOCK_WORDING,
    Adjustment,
    CalculationResult,
    EscalationRecord,
    TaxEntityProfile,
    TaxPeriodRevenue,
)

PENDING_FTA = "configured, pending FTA confirmation"
TEST_DATA = "test data, not confirmed"
FLAGGED_KINDS = ("exempt_income", "non_deductible", "interest_limit", "related_party", "transfer_pricing", "unrealised_gains", "group_relief", "foreign_income", "pre_regime_loss", "unclassified")


# --- rule lookup -------------------------------------------------------------------------------


def rule_lookup(db: Session, family: str, on_date: date) -> RuleRegisterEntry | None:
    """The rule-register row of the family (e.g. 'ct-rate') effective on the date, across versions, or None.

    Rows with parameters.applicable == False (e.g. a 'to be confirmed' extension) are never applied.
    """
    rows = db.scalars(select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id.like(f"{family}-v%"), RuleRegisterEntry.effective_from.is_not(None)).order_by(RuleRegisterEntry.effective_from.desc()))
    for r in rows:
        if (r.parameters or {}).get("applicable", True) is False:
            continue
        if r.effective_from and r.effective_from <= on_date and (r.effective_to is None or r.effective_to >= on_date):
            return r
    return None


def current_rule(db: Session, family: str) -> RuleRegisterEntry | None:
    rows = list(db.scalars(select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id.like(f"{family}-v%"), RuleRegisterEntry.is_current.is_(True))))
    rows = [r for r in rows if (r.parameters or {}).get("applicable", True) is not False]
    return rows[0] if rows else None


def rule_ref(r: RuleRegisterEntry | None) -> dict | None:
    if r is None:
        return None
    return {"rule_id": r.rule_id, "version": r.version, "instrument": r.instrument, "effective_from": r.effective_from.isoformat() if r.effective_from else None, "effective_to": r.effective_to.isoformat() if r.effective_to else None, "status": r.status, "confirmed_by": r.confirmed_by, "source": r.source, "label": TEST_DATA if r.status != "confirmed" else "confirmed"}


# --- profile -----------------------------------------------------------------------------------


def get_profile(db: Session, company_id: str) -> TaxEntityProfile:
    p = db.get(TaxEntityProfile, company_id)
    if p is None:
        co = db.get(Company, company_id)
        p = TaxEntityProfile(company_id=company_id, financial_year_end_month=co.financial_year_end_month if co else 12, financial_year_end_day=co.financial_year_end_day if co else 31)
        db.add(p)
        db.flush()
    return p


def update_profile(db: Session, company_id: str, actor: Any, **fields: Any) -> TaxEntityProfile:
    p = get_profile(db, company_id)
    for k, v in fields.items():
        if v is not None and hasattr(p, k):
            setattr(p, k, v)
    if fields.get("revenue_fils") is not None:
        p.revenue_confirmed_by, p.revenue_confirmed_at = actor.display_name, utcnow()
        p.revenue_source = fields.get("revenue_source") or p.revenue_source or "books (IFRS for SMEs), owner to confirm"
    p.updated_at = utcnow()
    record_event(db, event_type="TAX_PROFILE_UPDATED", category="config", actor_key=actor.actor_key, company_id=company_id, details={"fields": sorted(k for k, v in fields.items() if v is not None)})
    db.flush()
    return p


def profile_dict(p: TaxEntityProfile) -> dict:
    return {"company_id": p.company_id, "trn": p.trn, "vat_registered": p.vat_registered, "vat_period_type": p.vat_period_type, "ct_status": p.ct_status, "ct_status_source": p.ct_status_source, "financial_year_end_month": p.financial_year_end_month, "financial_year_end_day": p.financial_year_end_day, "first_ct_period_start": p.first_ct_period_start.isoformat() if p.first_ct_period_start else None, "sbr_election": p.sbr_election, "revenue_fils": p.revenue_fils, "revenue_source": p.revenue_source, "revenue_confirmed_by": p.revenue_confirmed_by, "revenue_confirmed_at": p.revenue_confirmed_at.isoformat() if p.revenue_confirmed_at else None, "related_party_declared": p.related_party_declared, "mne_group_eur_750m": p.mne_group_eur_750m}


def completeness_facts(db: Session, company_id: str, return_type: str) -> dict[str, bool]:
    p = get_profile(db, company_id)
    if return_type == "vat":
        return {"trn": bool(p.trn)}
    return {"ct_status": p.ct_status != "unclear", "financial_year": bool(p.financial_year_end_month), "revenue_confirmed": p.revenue_confirmed_at is not None}


def period_for(db: Session, company_id: str, period_id: str) -> tuple[date, date]:
    p = get_profile(db, company_id)
    return bk.period_bounds(period_id, p.financial_year_end_month, p.financial_year_end_day)


# --- due date (E3-S2 precedence: authority > user-confirmed > computed) --------------------------


def due_date_for(db: Session, company_id: str, tax_type: str, period_end: date) -> tuple[date | None, str]:
    try:
        from app.modules.deadlines.service import due_date_for as ext  # type: ignore

        d = ext(db, company_id, tax_type, period_end)
        if d:
            return d["date"] if isinstance(d, dict) else d[0], (d.get("source") if isinstance(d, dict) else d[1])
    except Exception:
        pass
    if tax_type == "vat":
        r = rule_lookup(db, "vat-return-due", period_end)
        if r:
            return period_end + timedelta(days=int(r.parameters.get("days_after_period_end", 28))), "computed"
        return None, "no_rule"
    r = rule_lookup(db, "ct-return-due", period_end)
    if r:
        return period_end + timedelta(days=int(r.parameters.get("months_after_period_end", 9)) * 30), "computed"
    return None, "no_rule"


# --- helpers -----------------------------------------------------------------------------------


def _next_version(db: Session, company_id: str, tax_type: str, period_id: str) -> int:
    last = db.scalar(select(CalculationResult.version).where(CalculationResult.company_id == company_id, CalculationResult.tax_type == tax_type, CalculationResult.period_id == period_id).order_by(CalculationResult.version.desc()).limit(1))
    return (last or 0) + 1


def latest(db: Session, company_id: str, tax_type: str, period_id: str) -> CalculationResult | None:
    return db.scalar(select(CalculationResult).where(CalculationResult.company_id == company_id, CalculationResult.tax_type == tax_type, CalculationResult.period_id == period_id).order_by(CalculationResult.version.desc()).limit(1))


def _no_rule_stop(db: Session, company_id: str, tax_type: str, period_id: str, start: date, end: date, family: str, actor_key: str | None) -> CalculationResult:
    ref = reference_code()
    calc = CalculationResult(company_id=company_id, tax_type=tax_type, period_id=period_id, period_start=start, period_end=end, version=_next_version(db, company_id, tax_type, period_id), state="no_rule_stop", state_reason=f"no rule row of '{family}' covers {end.isoformat()}", outputs=None, trace=[], notification_ref=ref, notification_sent_at=utcnow(), created_by_key=actor_key)
    db.add(calc)
    db.flush()
    record_event(db, event_type="NO_RULE_STOP", category="escalation", outcome="blocked", reason_code="NO_RULE", actor_key=actor_key, company_id=company_id, subject_type="calculation", subject_id=calc.id, details={"tax_type": tax_type, "period_id": period_id, "notification_ref": ref, "family": family})
    return calc


def _escalate(db: Session, calc: CalculationResult, trigger_id: str, *, amount_fils: int | None, note: str, actor_key: str | None) -> EscalationRecord:
    hours = int(get_config(db, "tax.escalation.expected_response_hours", 48) or 48)
    esc = EscalationRecord(company_id=calc.company_id, tax_type=calc.tax_type, period_id=calc.period_id, calculation_id=calc.id, trigger_id=trigger_id, amount_fils=amount_fils, rule_version=calc.rule_version, status=ESCALATED_STATUS, expected_response_hours=hours, notes=[{"note": note, "at": utcnow().isoformat()}], created_by_key=actor_key)
    db.add(esc)
    db.flush()
    try:  # hand over to the escalation module (E8) when it offers a case opener
        from app.modules.escalation.service import open_case  # type: ignore

        open_case(db, company_id=calc.company_id, kind="tax", reference=esc.id, trigger=trigger_id)
    except Exception:
        pass
    record_event(db, event_type="ESCALATION_CREATED", category="escalation", actor_key=actor_key, company_id=calc.company_id, subject_type="tax_escalation", subject_id=esc.id, details={"trigger_id": trigger_id, "tax_type": calc.tax_type, "period_id": calc.period_id, "status": ESCALATED_STATUS})
    return esc


def _round_fils(x: float) -> int:
    return int(round(x))


# --- VAT (vat-tp-v1) ---------------------------------------------------------------------------


def tax_point(txn: Any) -> tuple[date, str]:
    """vat-tp-v1: earliest of supply date, invoice date, payment (booking) date; credit note = issue date."""
    if txn.is_credit_note:
        return (txn.invoice_date or txn.txn_date), "credit-note issue date"
    candidates = [(txn.supply_date, "date of supply"), (txn.invoice_date, "tax invoice issue date"), (txn.txn_date, "payment received (booking date)")]
    best = min((d, n) for d, n in candidates if d is not None)
    return best


def dedup_key(txn: Any) -> tuple:
    return ((txn.counterparty or "").strip().lower(), txn.original_amount_fils, txn.original_currency, (txn.invoice_number or "").strip().lower())


PRECEDENCE = {"einvoice": 0, "ledger": 1, "bank": 2, "manual": 3}


def build_vat_lines(db: Session, rows: list[tuple[Any, Any]], rate_rule: RuleRegisterEntry) -> tuple[list[dict], list[dict]]:
    """One supply = one VAT line. Returns (lines, review_items). Review items are never calculated."""
    groups: dict[tuple, list[tuple[Any, Any]]] = {}
    for c, t in rows:
        groups.setdefault(dedup_key(t), []).append((c, t))
    lines: list[dict] = []
    review: list[dict] = []
    for key, members in groups.items():
        members.sort(key=lambda ct: PRECEDENCE.get(ct[1].source_kind, 9))
        doc_cls, doc = members[0]
        linked = [{"source_kind": t.source_kind, "source_system": t.source_system, "source_id": t.source_id, "pull_time": t.pull_time.isoformat(), "consent_id": t.consent_id} for _, t in members]
        if key[3]:  # invoice number: check e-invoice vs ERP disagreement on amount or VAT
            amounts = {(t.aed_amount_fils, t.vat_amount_stated_fils) for _, t in members if t.source_kind in ("einvoice", "ledger")}
            if len(amounts) > 1:
                review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": "e-invoice and ERP disagree on amount or VAT: exception for owner/accountant review", "sources": linked})
                continue
        else:
            kinds = {t.source_kind for _, t in members}
            if len(members) > 1 and len(kinds) == 1:
                review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": "possible duplicate (no auto-merge)", "sources": linked})
                continue
        if doc.special_sector or (doc_cls.final_vat_code == "RC"):
            review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": f"special sector / reverse charge ({doc.special_sector or 'RC'}): human review in Phase 1", "sources": linked})
            continue
        if doc.fx_missing:
            review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": "missing FX rate on the tax-point date: blocking exception, never estimated", "sources": linked})
            continue
        if doc.source_kind == "bank" and not doc.invoice_number and doc.direction == "in" and doc_cls.final_category == "sales_revenue" and doc_cls.basis_rule is None:
            review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": "unmatched, needs owner classification", "sources": linked})
            continue
        tp_date, tp_rule = tax_point(doc)
        bank_member = next((t for _, t in members if t.source_kind == "bank"), None)
        if bank_member is not None and bank_member.txn_date < tp_date:
            tp_date, tp_rule = bank_member.txn_date, "payment received (bank booking date brings the tax point forward)"
        vc = bk.vat_code_for(db, doc_cls.final_vat_code, tp_date)
        if vc is None:
            review.append({"classification_id": doc_cls.id, "date": doc.txn_date.isoformat(), "description": doc.description, "aed_amount_fils": doc.aed_amount_fils, "reason": "no VAT code effective on the tax-point date", "sources": linked})
            continue
        rate = float(vc.rate_percent)
        gross_basis = doc.source_kind in ("bank", "manual")
        amount = doc.aed_amount_fils
        if doc.vat_amount_stated_fils is not None:
            vat = doc.vat_amount_stated_fils
            net = amount - vat if gross_basis else amount
            vat_basis = "AED VAT amount stated on the tax invoice (issuer's conversion governs)"
        elif gross_basis:
            vat = _round_fils(amount * rate / (100 + rate))
            net = amount - vat
            vat_basis = f"gross x {rate}/(100+{rate})"
        else:
            net = amount
            vat = _round_fils(amount * rate / 100)
            vat_basis = f"net x {rate}%"
        sign = -1 if doc.is_credit_note else 1
        side = "output" if doc.direction == "in" else "input"
        if side == "input" and not vc.recoverable:
            vat_recoverable = 0
        else:
            vat_recoverable = vat
        lines.append({
            "classification_id": doc_cls.id,
            "date": doc.txn_date.isoformat(),
            "description": doc.description,
            "counterparty": doc.counterparty,
            "side": side,
            "vat_code": vc.code,
            "vat_code_version": vc.version_id,
            "vat_code_label": PENDING_FTA,
            "return_box_ref": vc.return_box_ref,
            "rate_percent": rate,
            "rate_rule": {"rule_id": rate_rule.rule_id, "version": rate_rule.version},
            "tax_point_date": tp_date.isoformat(),
            "tax_point_rule": tp_rule,
            "net_fils": sign * net,
            "vat_fils": sign * (vat_recoverable if side == "input" else vat),
            "vat_basis": vat_basis,
            "fx": {"rate": doc.fx_rate, "source": doc.fx_rate_source, "rate_date": doc.fx_rate_date.isoformat() if doc.fx_rate_date else None, "carried": doc.fx_carried} if doc.original_currency != "AED" else None,
            "credit_note": doc.is_credit_note,
            "original_invoice_ref": doc.original_invoice_ref,
            "source_documents": linked,
            "document_of_record": doc.source_kind,
            "line_class": "calculated",
            "review_status": "draft, not reviewed",
        })
    return lines, review


def registration_indicator(db: Session, taxable_supplies_12m_fils: int, on_date: date) -> dict:
    r = rule_lookup(db, "vat-registration", on_date)
    if r is None:
        return {"status": "no_rule"}
    mandatory = int(r.parameters["mandatory_fils"])
    voluntary = int(r.parameters["voluntary_fils"])
    return {"taxable_supplies_12m_fils": taxable_supplies_12m_fils, "mandatory_threshold_fils": mandatory, "voluntary_threshold_fils": voluntary, "must_register": taxable_supplies_12m_fils > mandatory, "voluntary_only": voluntary <= taxable_supplies_12m_fils <= mandatory, "rule": rule_ref(r), "note": "indicator only; registration is the taxpayer's own act"}


def calculate_vat(db: Session, company_id: str, period_id: str, *, actor: Any | None = None) -> CalculationResult:
    actor_key = getattr(actor, "actor_key", None)
    start, end = period_for(db, company_id, period_id)
    profile = get_profile(db, company_id)
    rate_rule = rule_lookup(db, "vat-rate", end)
    tp_rule = rule_lookup(db, "vat-tp", end)
    if rate_rule is None or tp_rule is None:
        return _no_rule_stop(db, company_id, "vat", period_id, start, end, "vat-rate" if rate_rule is None else "vat-tp", actor_key)
    rows = bk.confirmed_transactions(db, company_id, start, end)
    excluded = bk.excluded_transactions(db, company_id, start, end)
    missing_code = [c for c, _ in rows if not c.final_vat_code]
    version = _next_version(db, company_id, "vat", period_id)
    due, due_src = due_date_for(db, company_id, "vat", end)
    refs = {"vat-rate": rule_ref(rate_rule), "vat-tp": rule_ref(tp_rule), "vat-return-due": rule_ref(rule_lookup(db, "vat-return-due", end))}
    rule_version = ", ".join(f"{k}:{v['version']}" for k, v in refs.items() if v)
    cur = current_rule(db, "vat-rate")
    base = dict(company_id=company_id, tax_type="vat", period_id=period_id, period_start=start, period_end=end, version=version, rule_version=rule_version, current_rule_version=f"vat-rate:{cur.version}" if cur else None, rule_refs=refs, due_date=due, due_date_source=due_src, created_by_key=actor_key, inputs={"period_type": profile.vat_period_type, "trn": profile.trn, "confirmed_transactions": len(rows)}, inputs_source={"transactions": "classified", "period_type": "company-entered", "trn": "company-entered"})
    if missing_code:
        calc = CalculationResult(**base, state="missing_vat_code", state_reason=f"{len(missing_code)} transactions have no VAT code", excluded_items=[{"classification_id": c.id, "reason": "no VAT code"} for c in missing_code], excluded_count=len(missing_code), outputs=None, trace=[])
        db.add(calc)
        db.flush()
        record_event(db, event_type="CALCULATION_STOPPED", category="agent", outcome="blocked", reason_code="MISSING_VAT_CODE", actor_key=actor_key, company_id=company_id, subject_type="calculation", subject_id=calc.id, details={"n": len(missing_code)})
        return calc
    lines, review = build_vat_lines(db, rows, rate_rule)
    output_vat = sum(ln["vat_fils"] for ln in lines if ln["side"] == "output")
    input_vat = sum(ln["vat_fils"] for ln in lines if ln["side"] == "input")
    boxes: dict[str, int] = {}
    for ln in lines:
        if ln["return_box_ref"]:
            boxes[ln["return_box_ref"]] = boxes.get(ln["return_box_ref"], 0) + ln["vat_fils"]
    all_excluded = excluded + review
    taxable_12m = sum(ln["net_fils"] for ln in lines if ln["side"] == "output" and ln["vat_code"] in ("SR", "ZR"))
    outputs = {
        "output_vat_fils": output_vat,
        "input_vat_fils": input_vat,
        "net_vat_fils": output_vat - input_vat,
        "net_direction": "payable" if output_vat - input_vat >= 0 else "refundable",
        "lines": lines,
        "boxes": boxes,
        "box_mapping_label": PENDING_FTA,
        "fx_source_label": PENDING_FTA,
        "rounding": {"display_decimals": get_config(db, "tax.rounding.display_decimals", 2), "label": "display default only, provisional"},
        "registration": registration_indicator(db, taxable_12m, end),
        "sbr_note": "Small Business Relief has no effect on VAT",
        "label": DRAFT_LABEL,
        "estimates_statement": "Figures are estimates until the instruments are verified.",
    }
    trace = [
        {"step": "confirmed transactions in period", "count": len(rows), "source": "classified (posted entries)"},
        {"step": "tax point per line (vat-tp-v1)", "rule": refs["vat-tp"]},
        {"step": "rate per VAT code effective on the tax-point date", "rule": refs["vat-rate"], "vat_code_list": "vat-codes-v1 (configured, pending FTA confirmation)"},
        {"step": "output VAT - input VAT = net", "output_vat_fils": output_vat, "input_vat_fils": input_vat, "net_vat_fils": output_vat - input_vat},
        {"step": "due date", "date": due.isoformat() if due else None, "source": due_src},
    ]
    state = "incomplete" if all_excluded else "current"
    if not rows and not all_excluded:
        state = "current"
    calc = CalculationResult(**base, state=state, state_reason=None if state == "current" else f"Excludes {len(all_excluded)} items", excluded_items=all_excluded, excluded_count=len(all_excluded), excluded_total_fils=sum(int(e.get("aed_amount_fils") or 0) for e in all_excluded), outputs=outputs, trace=trace, data_hash=bk.data_hash(db, company_id, start, end))
    db.add(calc)
    db.flush()
    record_event(db, event_type="CALCULATION_RUN", category="agent", actor_key=actor_key, company_id=company_id, subject_type="calculation", subject_id=calc.id, details={"tax_type": "vat", "period_id": period_id, "version": version, "state": state, "rule_version": rule_version, "excluded": len(all_excluded)})
    return calc


# --- corporate tax --------------------------------------------------------------------------------


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def sbr_indicator(db: Session, *, period_start: date, period_end: date, revenue_fils: int | None, revenue_source: str | None, prior_revenues: list[int], exclusions: dict[str, bool], pro_rate: bool | None, election: str) -> dict:
    """Small Business Relief: an eligibility indicator only (Q94). Never 'applicable' or 'granted'."""
    r = rule_lookup(db, "sbr", period_end)
    cutoff_row = current_rule(db, "sbr")
    cutoff = cutoff_row.effective_to if cutoff_row else None
    out: dict[str, Any] = {"instrument": "Ministerial Decision 73/2023", "rule": rule_ref(r or cutoff_row), "revenue_fils": revenue_fils, "revenue_source": revenue_source or "owner to confirm", "period_end": period_end.isoformat(), "cutoff_date": cutoff.isoformat() if cutoff else None, "election_status": election, "review_status": "not reviewed", "label": "indicator only, not a decision; election is the taxpayer's own act, made in the return", "line_class": "calculated"}
    if r is None:
        out |= {"indicator": "not eligible", "text": "not eligible", "reason": f"period ends after {cutoff.strftime('%d %b %Y') if cutoff else 'the held relief end date'}", "election_allowed": False}
        return out
    limit = int(r.parameters["revenue_limit_fils"])
    pro = bool(r.parameters.get("pro_rate", False)) if pro_rate is None else pro_rate
    months = _months(period_start, period_end)
    eff_limit = _round_fils(limit * months / 12) if pro and months != 12 else limit
    reasons = []
    if revenue_fils is None:
        reasons.append("revenue not confirmed")
    elif revenue_fils > eff_limit:
        reasons.append(f"revenue above AED {eff_limit / 100:,.0f}")
    if any(pr > limit for pr in prior_revenues):
        reasons.append("revenue above the limit in a previous tax period")
    for k, v in exclusions.items():
        if v:
            reasons.append(f"excluded: {k}")
    eligible = not reasons
    out |= {"indicator": "may be eligible" if eligible else "not eligible", "text": "eligible, election needed" if eligible else "not eligible", "reason": None if eligible else "; ".join(reasons), "election_allowed": eligible, "revenue_limit_fils": eff_limit, "pro_rate": pro, "period_months": months, "prior_periods_checked": len(prior_revenues), "exclusions": exclusions}
    return out


def calculate_ct(db: Session, company_id: str, period_id: str, *, actor: Any | None = None, accounting_profit_fils: int | None = None, revenue_fils: int | None = None, revenue_source: str | None = None, prior_revenues: list[int] | None = None, adjustments: list[dict] | None = None, loss_cf_fils: int | None = None, sbr_election: str | None = None, pro_rate: bool | None = None) -> CalculationResult:
    """Corporate tax for a standalone DET mainland company only; tax group / QFZP / unclear are blocked."""
    actor_key = getattr(actor, "actor_key", None)
    start, end = period_for(db, company_id, period_id)
    profile = get_profile(db, company_id)
    version = _next_version(db, company_id, "ct", period_id)
    base = dict(company_id=company_id, tax_type="ct", period_id=period_id, period_start=start, period_end=end, version=version, created_by_key=actor_key)
    if profile.ct_status != "standalone_mainland":
        calc = CalculationResult(**base, state="blocked", state_reason=SCOPE_BLOCK_WORDING, outputs={"blocked": True, "wording": SCOPE_BLOCK_WORDING, "ct_status": profile.ct_status, "ct_status_source": profile.ct_status_source, "escalation_state": ESCALATED_STATUS, "label": DRAFT_LABEL}, trace=[], inputs={"ct_status": profile.ct_status}, inputs_source={"ct_status": "company-entered"})
        db.add(calc)
        db.flush()
        esc = _escalate(db, calc, "scope", amount_fils=None, note=f"ct_status={profile.ct_status}", actor_key=actor_key)
        calc.escalation_ids = [esc.id]
        record_event(db, event_type="CALCULATION_BLOCKED", category="escalation", outcome="blocked", reason_code="OUT_OF_SCOPE", actor_key=actor_key, company_id=company_id, subject_type="calculation", subject_id=calc.id, details={"ct_status": profile.ct_status})
        return calc
    rate_rule = rule_lookup(db, "ct-rate", end)
    if rate_rule is None or start < date.fromisoformat(str(rate_rule.parameters.get("applies_from", "2023-06-01"))):
        return _no_rule_stop(db, company_id, "ct", period_id, start, end, "ct-rate", actor_key)
    rows = bk.confirmed_transactions(db, company_id, start, end)
    excluded = bk.excluded_transactions(db, company_id, start, end)
    income = sum(t.aed_amount_fils for c, t in rows if (c.final_ledger_account or "").startswith(bk.INCOME_ACCOUNT_PREFIX))
    expenses = sum(t.aed_amount_fils for c, t in rows if (c.final_ledger_account or "").startswith(("5", "6")))
    profit_books = income - expenses
    profit = accounting_profit_fils if accounting_profit_fils is not None else profit_books
    profit_source = "company-entered" if accounting_profit_fils is not None else "classified"
    revenue = revenue_fils if revenue_fils is not None else profile.revenue_fils
    rev_source = revenue_source or profile.revenue_source or ("books, owner to confirm" if revenue is not None else None)
    if prior_revenues is None:
        first = profile.first_ct_period_start or date(2023, 6, 1)
        prior_revenues = [r.revenue_fils for r in db.scalars(select(TaxPeriodRevenue).where(TaxPeriodRevenue.company_id == company_id, TaxPeriodRevenue.period_end < start, TaxPeriodRevenue.period_start >= first))]
    # adjustments: stored person-entered/flagged rows for the period plus any passed in this run
    stored = list(db.scalars(select(Adjustment).where(Adjustment.company_id == company_id, Adjustment.period_id == period_id)))
    adj_rows: list[dict] = []
    for a in stored:
        adj_rows.append({"id": a.id, "class": a.adjustment_class, "kind": a.kind, "label": a.label, "amount_fils": a.amount_fils, "reason": a.reason, "related_party": a.related_party, "entered_by": a.entered_by_name, "review_status": a.review_status, "held_for_specialist": a.held_for_specialist})
    for a in adjustments or []:
        cls_ = a.get("class", "person_entered")
        rp = bool(a.get("related_party"))
        adj_rows.append({"id": None, "class": "flagged" if rp else cls_, "kind": a.get("kind", "other"), "label": a.get("label", a.get("kind", "adjustment")), "amount_fils": int(a.get("amount_fils", 0)), "reason": a.get("reason"), "related_party": rp, "entered_by": getattr(actor, "display_name", None), "review_status": "flagged, held for specialist review" if rp or cls_ == "flagged" else "person-entered, not reviewed", "held_for_specialist": rp or cls_ == "flagged"})
    flagged = [a for a in adj_rows if a["class"] == "flagged" or a["related_party"]]
    person_entered = [a for a in adj_rows if a["class"] == "person_entered" and not a["related_party"]]
    adj_total = sum(a["amount_fils"] for a in adj_rows)
    ti_before_loss = profit + adj_total
    loss_rule = rule_lookup(db, "ct-loss-cf", end)
    cap_pct = int(loss_rule.parameters.get("cap_percent", 75)) if loss_rule else 75
    loss_applied = 0
    if loss_cf_fils:
        loss_applied = min(int(loss_cf_fils), _round_fils(max(ti_before_loss, 0) * cap_pct / 100))
    taxable_income = ti_before_loss - loss_applied
    threshold = int(rate_rule.parameters["threshold_fils"])
    rate = float(rate_rule.parameters["rate_percent"])
    band0 = min(max(taxable_income, 0), threshold)
    band9 = max(taxable_income - threshold, 0)
    tax_normal = _round_fils(band9 * rate / 100)
    election = sbr_election or profile.sbr_election
    sbr = sbr_indicator(db, period_start=start, period_end=end, revenue_fils=revenue, revenue_source=rev_source, prior_revenues=prior_revenues, exclusions={"qfzp": profile.ct_status == "qfzp", "mne_group_eur_750m": profile.mne_group_eur_750m}, pro_rate=pro_rate, election=election)
    sbr["tax_if_elected_fils"] = 0 if sbr["election_allowed"] else tax_normal
    sbr["tax_if_not_elected_fils"] = tax_normal
    tax = 0 if (sbr["election_allowed"] and election == "elected") else tax_normal
    audit_rule = rule_lookup(db, "ct-audit-required", end)
    audit_required = None
    if audit_rule:
        audit_required = {"required": bool(revenue is not None and revenue > int(audit_rule.parameters["revenue_fils"])) or profile.ct_status in ("qfzp", "tax_group"), "rule": rule_ref(audit_rule), "basis": "revenue above AED 50m, QFZP or tax group"}
    einv = current_rule(db, "einvoicing")
    due, due_src = due_date_for(db, company_id, "ct", end)
    refs = {"ct-rate": rule_ref(rate_rule), "sbr": sbr["rule"], "ct-loss-cf": rule_ref(loss_rule), "ct-audit-required": rule_ref(audit_rule), "einvoicing": rule_ref(einv)}
    rule_version = ", ".join(f"{k}:{v['version']}" for k, v in refs.items() if v)
    cur = current_rule(db, "ct-rate")
    outputs = {
        "accounting_profit_fils": profit,
        "accounting_profit_source": profit_source,
        "books": {"income_fils": income, "expenses_fils": expenses, "profit_fils": profit_books, "confirmed_transactions": len(rows)},
        "adjustments": adj_rows,
        "flagged_items": flagged,
        "person_entered_items": person_entered,
        "adjustments_total_fils": adj_total,
        "loss_carry_forward": {"entered_fils": loss_cf_fils or 0, "applied_fils": loss_applied, "cap_percent": cap_pct, "line_class": "calculated", "note": "opening balance and eligibility person-entered and confirmed"},
        "taxable_income_fils": taxable_income,
        "band_0_fils": band0,
        "band_9_fils": band9,
        "threshold_fils": threshold,
        "rate_percent": rate,
        "tax_normal_fils": tax_normal,
        "tax_fils": tax,
        "sbr": sbr,
        "audit_required": audit_required,
        "einvoicing_flag": {"date_flag_only": True, "rule": rule_ref(einv)},
        "label": DRAFT_LABEL,
        "estimates_statement": "Figures are estimates until the instruments are verified.",
        "lines": [
            {"key": "accounting_profit", "amount_fils": profit, "line_class": "calculated" if profit_source == "classified" else "person_entered", "source": profit_source},
            *[{"key": f"adjustment:{a['kind']}", "amount_fils": a["amount_fils"], "line_class": a["class"], "source": "company-entered", "held_for_specialist": a["held_for_specialist"]} for a in adj_rows],
            {"key": "loss_carry_forward", "amount_fils": -loss_applied, "line_class": "calculated", "source": "company-entered"},
            {"key": "taxable_income", "amount_fils": taxable_income, "line_class": "calculated", "source": "calculated"},
            {"key": "tax", "amount_fils": tax, "line_class": "calculated", "source": "calculated"},
        ],
    }
    trace = [
        {"step": "accounting profit from the books (income - expenses on confirmed entries)", "income_fils": income, "expenses_fils": expenses, "source": profit_source},
        {"step": "adjustments (calculated | flagged | person-entered)", "total_fils": adj_total, "flagged": len(flagged)},
        {"step": f"loss carry-forward capped at {cap_pct}% of taxable income", "applied_fils": loss_applied, "rule": refs["ct-loss-cf"]},
        {"step": "0% / 9% band split", "band_0_fils": band0, "band_9_fils": band9, "rule": refs["ct-rate"]},
        {"step": "Small Business Relief indicator (eligibility only)", "indicator": sbr["indicator"], "rule": refs["sbr"]},
        {"step": "due date", "date": due.isoformat() if due else None, "source": due_src},
    ]
    state = "incomplete" if excluded else "current"
    calc = CalculationResult(**base, rule_version=rule_version, current_rule_version=f"ct-rate:{cur.version}" if cur else None, rule_refs=refs, inputs={"accounting_profit_fils": profit, "revenue_fils": revenue, "prior_revenues": prior_revenues, "loss_cf_fils": loss_cf_fils, "sbr_election": election, "pro_rate": sbr.get("pro_rate")}, inputs_source={"accounting_profit": profit_source, "revenue": "company-entered", "adjustments": "company-entered", "transactions": "classified"}, state=state, state_reason=None if state == "current" else f"Excludes {len(excluded)} items", excluded_items=excluded, excluded_count=len(excluded), excluded_total_fils=sum(int(e["aed_amount_fils"]) for e in excluded), outputs=outputs, trace=trace, due_date=due, due_date_source=due_src, data_hash=bk.data_hash(db, company_id, start, end))
    db.add(calc)
    db.flush()
    # Escalation triggers 1-5 (provisional, versioned config ct-escalation-v1)
    esc_rule = rule_lookup(db, "ct-escalation", end)
    esc_ids: list[str] = []
    if esc_rule:
        p = esc_rule.parameters
        for a in flagged:
            esc_ids.append(_escalate(db, calc, "1", amount_fils=a["amount_fils"], note=f"flagged item: {a['kind']}", actor_key=actor_key).id)
        t2_limit = max(_round_fils(abs(profit) * float(p["t2_pct_of_profit"]) / 100), int(p["t2_abs_fils"]))
        for a in person_entered:
            if abs(a["amount_fils"]) >= t2_limit:
                esc_ids.append(_escalate(db, calc, "2", amount_fils=a["amount_fils"], note="person-entered adjustment at or above the larger of 5% of accounting profit or AED 50,000", actor_key=actor_key).id)
        if adj_total and ((profit <= threshold) != (ti_before_loss <= threshold)):
            esc_ids.append(_escalate(db, calc, "2", amount_fils=adj_total, note="adjustments together cross the AED 375,000 taxable income line", actor_key=actor_key).id)
        prev = db.scalar(select(CalculationResult).where(CalculationResult.company_id == company_id, CalculationResult.tax_type == "ct", CalculationResult.period_id == period_id, CalculationResult.version < version, CalculationResult.outputs.is_not(None)).order_by(CalculationResult.version.desc()).limit(1))
        if prev and prev.outputs and "tax_fils" in prev.outputs:
            delta = abs(tax - int(prev.outputs["tax_fils"]))
            if delta > int(p["t3_abs_fils"]) or (prev.outputs["tax_fils"] and delta / abs(int(prev.outputs["tax_fils"])) * 100 > float(p["t3_pct"])):
                esc_ids.append(_escalate(db, calc, "3", amount_fils=delta, note="tax payable changed by more than AED 10,000 or 10% against the previous version", actor_key=actor_key).id)
        lo, hi = p["t4_band_fils"]
        if revenue is not None and int(lo) <= revenue <= int(hi):
            esc_ids.append(_escalate(db, calc, "4", amount_fils=revenue, note="revenue within the near-threshold band of AED 50 million", actor_key=actor_key).id)
        bank_total = sum(t.aed_amount_fils for _, t in rows if t.source_kind == "bank")
        ledger_total = sum(t.aed_amount_fils for _, t in rows if t.source_kind in ("ledger", "einvoice"))
        if bank_total and ledger_total:
            mismatch = abs(bank_total - ledger_total) / max(bank_total, ledger_total) * 100
            if mismatch > float(p["t5_mismatch_tolerance_pct"]):
                esc_ids.append(_escalate(db, calc, "5", amount_fils=abs(bank_total - ledger_total), note="ledger vs bank data mismatch above the configured tolerance", actor_key=actor_key).id)
    calc.escalation_ids = esc_ids
    outputs["escalation_state"] = ESCALATED_STATUS if esc_ids else None
    outputs["escalations"] = [{"id": e.id, "trigger_id": e.trigger_id, "status": e.status, "expected_response_hours": e.expected_response_hours, "amount_fils": e.amount_fils} for e in db.scalars(select(EscalationRecord).where(EscalationRecord.id.in_(esc_ids)))] if esc_ids else []
    calc.outputs = dict(outputs)
    record_event(db, event_type="CALCULATION_RUN", category="agent", actor_key=actor_key, company_id=company_id, subject_type="calculation", subject_id=calc.id, details={"tax_type": "ct", "period_id": period_id, "version": version, "state": state, "rule_version": rule_version, "escalations": len(esc_ids)})
    db.flush()
    return calc


def add_adjustment(db: Session, company_id: str, period_id: str, actor: Any, *, kind: str, label: str, amount_fils: int, reason: str, related_party: bool = False, adjustment_class: str = "person_entered") -> Adjustment:
    if not reason or not reason.strip():
        raise ValidationFailed("an adjustment needs a reason", reason_code="REASON_REQUIRED")
    held = related_party or adjustment_class == "flagged" or kind in FLAGGED_KINDS
    a = Adjustment(company_id=company_id, period_id=period_id, adjustment_class="flagged" if held else adjustment_class, kind=kind, label=label, amount_fils=amount_fils, reason=reason, related_party=related_party, entered_by_name=actor.display_name, entered_by_role=bk.role_for(actor, company_id), review_status="flagged, held for specialist review" if held else "person-entered, not reviewed", held_for_specialist=held)
    db.add(a)
    db.flush()
    record_event(db, event_type="ADJUSTMENT_ENTERED", category="agent", actor_key=actor.actor_key, actor_role=a.entered_by_role, company_id=company_id, subject_type="adjustment", subject_id=a.id, details={"kind": kind, "class": a.adjustment_class, "related_party": related_party, "reason_recorded": True})
    return a


# --- read, staleness, review, comparison --------------------------------------------------------


def check_stale(db: Session, calc: CalculationResult) -> CalculationResult:
    """Confirmed transactions changed after the run -> 'stale', status reset to not reviewed (Q95 hash method)."""
    if calc.state in ("current", "incomplete") and calc.data_hash:
        now_hash = bk.data_hash(db, calc.company_id, calc.period_start, calc.period_end)
        if now_hash != calc.data_hash:
            calc.state = "stale"
            calc.state_reason = f"transactions changed after this calculation on {calc.created_at.isoformat()}"
            calc.review_status = "not_reviewed"
            record_event(db, event_type="CALCULATION_STALE", category="agent", company_id=calc.company_id, subject_type="calculation", subject_id=calc.id)
            db.flush()
    return calc


def mark_reviewed(db: Session, company_id: str, tax_type: str, period_id: str, actor: Any) -> CalculationResult:
    calc = latest(db, company_id, tax_type, period_id)
    if calc is None:
        raise NotFound("no calculation for this period", reason_code="NOT_FOUND")
    check_stale(db, calc)
    role = bk.role_for(actor, company_id)
    if role not in ("owner", "delegate") or not bk.has_function(actor, company_id, "tax_preparation"):
        raise Forbidden("You can view this calculation. You do not have the tax-preparation function.", reason_code="NO_FUNCTION")
    if calc.state != "current":
        raise Conflict("only a current, complete result can be marked as reviewed", reason_code="NOT_CURRENT", details={"state": calc.state})
    calc.review_status, calc.reviewed_by_name, calc.reviewed_by_role, calc.reviewed_at = "reviewed", actor.display_name, role, utcnow()
    record_event(db, event_type="CALCULATION_REVIEWED", category="agent", actor_key=actor.actor_key, actor_role=role, company_id=company_id, subject_type="calculation", subject_id=calc.id)
    db.flush()
    return calc


def comparison(db: Session, calc: CalculationResult) -> dict:
    """Phase 1B: earlier-rule-version comparison, information only; the figure of record never changes."""
    if calc.outputs is None or calc.state in ("blocked", "no_rule_stop"):
        return {"available": False}
    family = "vat-rate" if calc.tax_type == "vat" else "ct-rate"
    used = (calc.rule_refs or {}).get(family)
    cur = current_rule(db, family)
    if not used or cur is None or used["version"] == cur.version:
        return {"available": True, "same": True, "text": "Same result under current rules.", "used": used, "current": rule_ref(cur)}
    key = "net_vat_fils" if calc.tax_type == "vat" else "tax_fils"
    figure = int(calc.outputs.get(key, 0))
    if calc.tax_type == "ct":
        rate = float(cur.parameters["rate_percent"])
        threshold = int(cur.parameters["threshold_fils"])
        alt = _round_fils(max(int(calc.outputs["taxable_income_fils"]) - threshold, 0) * rate / 100)
    else:
        rate = float(cur.parameters["rate_percent"])
        alt = _round_fils(sum(ln["net_fils"] * (1 if ln["side"] == "output" else -1) for ln in calc.outputs["lines"] if ln["vat_code"] == "SR") * rate / 100)
    diff = alt - figure
    return {"available": True, "same": diff == 0, "used": used, "current": rule_ref(cur), "figure_fils": figure, "current_rules_figure_fils": alt, "difference_fils": diff, "word": "higher by" if diff > 0 else "lower by" if diff < 0 else None, "text": "Same result under current rules." if diff == 0 else "The earlier figure is the one for that period. This comparison is for information."}


def calc_dict(db: Session, calc: CalculationResult, *, role: str = "owner", summary_only: bool = False) -> dict:
    out = {
        "id": calc.id,
        "company_id": calc.company_id,
        "tax_type": calc.tax_type,
        "period_id": calc.period_id,
        "period_start": calc.period_start.isoformat(),
        "period_end": calc.period_end.isoformat(),
        "version": calc.version,
        "rule_version": calc.rule_version,
        "current_rule_version": calc.current_rule_version,
        "rule_refs": calc.rule_refs,
        "ai_prepared": True,
        "ai_label": "AI-prepared calculation. Status: not reviewed" if calc.review_status == "not_reviewed" else f"Reviewed by {calc.reviewed_by_name}, {calc.reviewed_by_role}, {calc.reviewed_at.date().isoformat() if calc.reviewed_at else ''}",
        "review_status": calc.review_status,
        "reviewed_by": {"name": calc.reviewed_by_name, "role": calc.reviewed_by_role, "at": calc.reviewed_at.isoformat() if calc.reviewed_at else None} if calc.reviewed_at else None,
        "state": calc.state,
        "state_reason": calc.state_reason,
        "label": calc.label,
        "estimates_statement": "Figures are estimates until the instruments are verified.",
        "not_advice": "This is a calculation, not tax advice. Complex case? Ask a specialist.",
        "due_date": calc.due_date.isoformat() if calc.due_date else None,
        "due_date_source": calc.due_date_source,
        "excluded_count": calc.excluded_count,
        "excluded_total_fils": calc.excluded_total_fils,
        "notification_ref": calc.notification_ref,
        "notification_sent_at": calc.notification_sent_at.isoformat() if calc.notification_sent_at else None,
        "created_at": calc.created_at.isoformat(),
        "can_approve": calc.state == "current",
        "approval_disabled_reason": None if calc.state == "current" else ("Approval is off until all items are reviewed." if calc.state == "incomplete" else calc.state_reason),
        "escalation_ids": calc.escalation_ids or [],
    }
    if summary_only:  # remote owner: net figure only if current and reviewed
        key = "net_vat_fils" if calc.tax_type == "vat" else "tax_fils"
        out["net_figure_fils"] = int(calc.outputs.get(key)) if (calc.outputs and calc.state == "current" and calc.review_status == "reviewed") else None
        out["summary_note"] = "Summary view. Detailed adjustments are made by your delegate or in the UAE portal session."
        return out
    out |= {"inputs": calc.inputs, "inputs_source": calc.inputs_source, "excluded_items": calc.excluded_items or [], "outputs": calc.outputs, "trace": calc.trace, "comparison": comparison(db, calc)}
    if calc.state == "no_rule_stop":
        start, end = calc.period_start, calc.period_end
        rows = bk.confirmed_transactions(db, calc.company_id, start, end)
        out["what_we_have"] = {"confirmed_transactions": len(rows), "needs_review": len(bk.excluded_transactions(db, calc.company_id, start, end))}
        out["outputs"] = None  # no figure, no partial totals
    return out


def hash_inputs(calc: CalculationResult) -> str:
    import json

    return hashlib.sha256(json.dumps({"inputs": calc.inputs, "data_hash": calc.data_hash, "rule_version": calc.rule_version, "version": calc.version}, sort_keys=True, default=str).encode()).hexdigest()[:16]

