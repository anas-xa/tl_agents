"""E7-S1 continuous review: consent gate, versioned exception rules AX01..AX08 (+AX01b), flag lineage and revisions,
reviewer decisions, K16, masking on withdrawal.

Flags are neutral 'items for review'. No confidence score is stored or shown. The cash rule is an internal analytical
rule, default OFF, labelled 'internal review threshold, not a legal limit'; no legal cash threshold exists in code.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.auditagent.models import (
    DECISION_TO_STATUS,
    DECISIONS,
    EvidenceMask,
    ExceptionFlag,
    ExceptionRule,
    ExceptionRuleOverride,
    FlagDecision,
    FlagRevision,
    ReviewCycle,
)
from app.modules.config.service import get_config

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
CASH_RULE_ID = "AXC1"

# Versioned rule register r1 (thresholds held as data; seeded into audit_exception_rules).
RULES_R1: list[dict[str, Any]] = [
    {"rule_id": "AX01", "title_en": "Possible duplicate invoice (exact match)", "title_ar": "فاتورة مكررة محتملة (تطابق تام)", "default_severity": "High", "legal_anchor": "anchored", "instrument": "Federal Decree-Law 8/2017 tax invoice rules (confirm)", "sources_read": ["ledger", "e_invoice"], "fields_read": ["counterparty", "invoice_number", "amount"], "parameters": {"normalise_invoice_number": ["trim", "case_fold", "strip_leading_zeros"], "amount_match": "exact to the fils"}, "phase": "1A", "label": "estimate, configurable", "approved_by_tax_specialist": "pilot tax specialist team lead (pending)"},
    {"rule_id": "AX01b", "title_en": "Possible duplicate payment (same counterparty and amount)", "title_ar": "دفعة مكررة محتملة (نفس الطرف والمبلغ)", "default_severity": "Low", "legal_anchor": "heuristic", "sources_read": ["ledger"], "fields_read": ["counterparty", "amount", "date", "invoice_number"], "parameters": {"window_days": 7}, "phase": "1A", "label": "estimate"},
    {"rule_id": "AX02", "title_en": "VAT amount does not match net amount and rate", "title_ar": "مبلغ الضريبة لا يطابق المبلغ الصافي والنسبة", "default_severity": "Medium", "legal_anchor": "anchored", "instrument": "Federal Decree-Law 8/2017 (confirm)", "sources_read": ["ledger", "e_invoice"], "fields_read": ["amount", "vat_code", "vat_amount"], "parameters": {"tolerance_fils_per_line": 100, "rate_source": "versioned VAT code reference data", "default_rate_percent": 5}, "phase": "1A", "label": "estimate", "approved_by_tax_specialist": "pilot tax specialist team lead (pending)"},
    {"rule_id": "AX03", "title_en": "Tax registration number missing or not valid on a VAT invoice", "title_ar": "رقم التسجيل الضريبي مفقود أو غير صالح في فاتورة ضريبية", "default_severity": "Medium", "legal_anchor": "anchored", "instrument": "Federal Decree-Law 8/2017 tax invoice fields (confirm)", "sources_read": ["ledger", "e_invoice"], "fields_read": ["trn", "amount", "vat_code"], "parameters": {"gross_threshold_fils": 1_000_000, "trn_digits": 15}, "phase": "1A", "label": "placeholder", "approved_by_tax_specialist": "pilot tax specialist team lead (pending)"},
    {"rule_id": "AX04", "title_en": "Bank movement with no matching ledger entry", "title_ar": "حركة بنكية بلا قيد مطابق في الدفاتر", "default_severity": "Medium", "legal_anchor": "heuristic", "sources_read": ["bank", "ledger"], "fields_read": ["amount", "date"], "parameters": {"min_amount_fils": 500_000, "match_window_days": 5, "min_age_days": 14, "holiday_widening_days": 3}, "bank_dependent": True, "phase": "bank", "label": "estimate"},
    {"rule_id": "AX05", "title_en": "Ledger entry with no matching bank movement", "title_ar": "قيد في الدفاتر بلا حركة بنكية مطابقة", "default_severity": "Low", "legal_anchor": "heuristic", "sources_read": ["bank", "ledger"], "fields_read": ["amount", "date"], "parameters": {"min_amount_fils": 500_000, "match_window_days": 7, "holiday_widening_days": 3}, "bank_dependent": True, "phase": "bank", "label": "estimate"},
    {"rule_id": "AX06", "title_en": "Round-amount entry near the end of a period", "title_ar": "قيد بمبلغ مقرّب قرب نهاية الفترة", "default_severity": "Low", "legal_anchor": "heuristic", "sources_read": ["ledger"], "fields_read": ["amount", "date"], "parameters": {"multiple_fils": 1_000_000, "last_days_of_period": 2}, "phase": "1A", "label": "estimate"},
    {"rule_id": "AX07", "title_en": "Entry dated outside the tax period or in the future", "title_ar": "قيد مؤرخ خارج الفترة الضريبية أو بتاريخ مستقبلي", "default_severity": "Medium", "legal_anchor": "anchored", "instrument": "period cut-off (configuration)", "sources_read": ["ledger"], "fields_read": ["date", "posted_date"], "parameters": {}, "phase": "1A", "label": "settled"},
    {"rule_id": "AX08", "title_en": "Large single movement compared with history", "title_ar": "حركة منفردة كبيرة مقارنة بالسجل", "default_severity": "Medium", "legal_anchor": "heuristic", "sources_read": ["bank"], "fields_read": ["amount", "date"], "parameters": {"floor_fils": 5_000_000, "multiple_of_median": 5, "trailing_months": 6, "min_history_months": 6}, "bank_dependent": True, "phase": "bank", "label": "estimate"},
    # Internal analytical rule, default OFF; no legal basis cited; never displayed as a legal limit.
    {"rule_id": CASH_RULE_ID, "title_en": "Cash transaction above an internal review threshold", "title_ar": "معاملة نقدية فوق حد مراجعة داخلي", "default_severity": "Low", "legal_anchor": "heuristic", "sources_read": ["ledger", "bank"], "fields_read": ["amount", "description"], "parameters": {"threshold_fils": None, "keywords": ["cash", "نقد", "نقدا", "نقدًا"]}, "phase": "1A", "enabled": False, "label": "internal review threshold, not a legal limit", "status": "to_be_confirmed"},
]

# Test hook: called after each batch is read (lets tests withdraw consent mid-cycle).
BATCH_HOOK: Callable[[Session, str, str, int], None] | None = None


def _int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_config(db, key, default))
    except (TypeError, ValueError):
        return default


def model_version() -> str:
    try:
        from app.modules.localmodel.client import get_local_model

        m = get_local_model()
        return str(getattr(m, "model_version", None) or "rules-v1")
    except Exception:  # pragma: no cover - adapter optional
        return "local-rules-v1"


# --- rule register ---------------------------------------------------------------------------------


def current_rules(db: Session) -> list[ExceptionRule]:
    return list(db.scalars(select(ExceptionRule).where(ExceptionRule.is_current.is_(True)).order_by(ExceptionRule.rule_id)))


def rule_row(r: ExceptionRule) -> dict:
    return {"rule_id": r.rule_id, "rule_version": r.rule_version, "title": {"en": r.title_en, "ar": r.title_ar}, "default_severity": r.default_severity, "legal_anchor": r.legal_anchor, "instrument": r.instrument if r.legal_anchor == "anchored" else None, "bank_dependent": r.bank_dependent, "phase": r.phase, "enabled": r.enabled, "label": r.label, "status": r.status, "parameters": r.parameters, "effective_date": r.effective_date.isoformat(), "owner": r.owner, "sources_read": r.sources_read}


def new_rule_version(db: Session, rule_id: str, *, parameters: dict, change_reason: str, owner: str, approved_by_tax_specialist: str | None = None) -> ExceptionRule:
    """A threshold change creates a new rule_version; flags keep the version they were raised under."""
    cur = db.scalar(select(ExceptionRule).where(ExceptionRule.rule_id == rule_id, ExceptionRule.is_current.is_(True)))
    if cur is None:
        raise NotFound("rule not found", reason_code="RULE_NOT_FOUND")
    if cur.legal_anchor == "anchored" and not approved_by_tax_specialist:
        raise ValidationFailed("rules tied to VAT or corporate tax need tax specialist approval", reason_code="TAX_SPECIALIST_APPROVAL_REQUIRED")
    n = int(re.sub(r"\D", "", cur.rule_version) or 1) + 1
    cur.is_current = False
    row = ExceptionRule(rule_id=rule_id, rule_version=f"r{n}", title_en=cur.title_en, title_ar=cur.title_ar, effective_date=date.today(), change_reason=change_reason, owner=owner, approved_by_tax_specialist=approved_by_tax_specialist, sources_read=cur.sources_read, fields_read=cur.fields_read, default_severity=cur.default_severity, parameters={**(cur.parameters or {}), **parameters}, bank_dependent=cur.bank_dependent, legal_anchor=cur.legal_anchor, instrument=cur.instrument, phase=cur.phase, enabled=cur.enabled, label=cur.label, status=cur.status)
    db.add(row)
    db.flush()
    record_event(db, event_type="EXCEPTION_RULE_VERSIONED", category="config", subject_type="exception_rule", subject_id=rule_id, details={"rule_version": row.rule_version})
    return row


def effective_rule(db: Session, company_id: str, rule: ExceptionRule) -> tuple[bool, dict]:
    ov = db.scalar(select(ExceptionRuleOverride).where(ExceptionRuleOverride.company_id == company_id, ExceptionRuleOverride.rule_id == rule.rule_id))
    if ov is None:
        return rule.enabled, dict(rule.parameters or {})
    return ov.enabled, {**(rule.parameters or {}), **(ov.parameters or {})}


def set_company_override(db: Session, company_id: str, rule_id: str, *, enabled: bool, parameters: dict | None, set_by: str) -> ExceptionRuleOverride:
    ov = db.scalar(select(ExceptionRuleOverride).where(ExceptionRuleOverride.company_id == company_id, ExceptionRuleOverride.rule_id == rule_id))
    if ov is None:
        ov = ExceptionRuleOverride(company_id=company_id, rule_id=rule_id)
        db.add(ov)
    ov.enabled, ov.parameters, ov.set_by, ov.set_at = enabled, parameters, set_by, utcnow()
    db.flush()
    record_event(db, event_type="EXCEPTION_RULE_OVERRIDE_SET", category="config", company_id=company_id, subject_type="exception_rule", subject_id=rule_id, details={"enabled": enabled})
    return ov


# --- consent gate ------------------------------------------------------------------------------------


def source_gate(db: Session, company_id: str, source: str, *, actor_key: str | None = None) -> dict:
    """Ledger/e-invoice need an active connector authorisation; bank needs open-finance consent. Fail closed."""
    kind = "bank" if source == "bank" else "ledger"
    try:
        from app.modules.bookkeeping.service import consent_state

        st = consent_state(db, company_id, kind)
    except ImportError:  # pragma: no cover
        return {"allowed": True, "state": "active", "ended_on": None}
    if st.get("allowed"):
        return st
    try:
        from app.modules.consent.service import check_consent

        consent_type, src = ("bank_data_open_finance", "bank") if kind == "bank" else ("ledger_invoice_authorisation", "erp")
        for purpose in get_config(db, "auditagent.review.accepted_purposes", ["audit_preparation", "bookkeeping_classification"]) or []:
            dec = check_consent(db, company_id, consent_type, {"source": src, "purpose": purpose}, actor_key=actor_key)
            if dec.allowed:
                return {**st, "allowed": True, "state": "active"}
    except Exception:  # gate unavailable -> deny
        pass
    return st


# --- record normalisation ----------------------------------------------------------------------------


def _norm_inv(v: str | None) -> str:
    return re.sub(r"(?<!\d)0+(?=\d)", "", re.sub(r"\s+", "", (v or "").strip().casefold()))


def _norm_cp(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().casefold())


def ledger_records(db: Session, company_id: str) -> list[dict]:
    from app.modules.bookkeeping.models import Classification, Transaction

    out = []
    rows = db.execute(select(Transaction, Classification).join(Classification, Classification.txn_id == Transaction.id, isouter=True).where(Transaction.company_id == company_id, Transaction.source_consent_withdrawn.is_(False)).order_by(Transaction.txn_date, Transaction.id)).all()
    for t, c in rows:
        out.append({
            "record_id": t.id, "record_version": (c.version if c else 1), "source": "ledger", "date": t.txn_date, "posted_date": (t.pull_time.date() if t.pull_time else t.txn_date),
            "amount_fils": t.aed_amount_fils, "direction": t.direction, "vat_fils": t.vat_amount_stated_fils, "vat_code": (c.final_vat_code or c.proposed_vat_code) if c else None,
            "account_code": (c.final_ledger_account or c.proposed_ledger_account) if c else None, "counterparty": t.counterparty, "invoice_number": t.invoice_number,
            "currency": t.original_currency, "description": t.description, "manual": t.source_kind == "manual", "trn": None, "has_trn_field": False,
        })
    return out


def bank_records(db: Session, company_id: str) -> list[dict]:
    try:
        from app.modules.datalinks.models import StatementLine, StatementUpload
    except ImportError:  # pragma: no cover
        return []
    out = []
    rows = db.execute(select(StatementLine, StatementUpload).join(StatementUpload, StatementUpload.upload_id == StatementLine.upload_id).where(StatementLine.company_id == company_id, StatementLine.data_use_flag == "active", StatementUpload.kind == "bank_statement").order_by(StatementLine.txn_date, StatementLine.id)).all()
    for ln, _up in rows:
        out.append({"record_id": f"sl{ln.id}", "record_version": 1, "source": "bank", "date": ln.txn_date, "posted_date": ln.txn_date, "amount_fils": abs(ln.amount_fils), "direction": "in" if ln.amount_fils >= 0 else "out", "vat_fils": None, "vat_code": None, "account_code": None, "counterparty": ln.counterparty, "invoice_number": None, "currency": ln.currency, "description": ln.description, "manual": True, "trn": None, "has_trn_field": False})
    return out


def _evidence_row(r: dict) -> dict:
    return {"record_id": r["record_id"], "record_version": r.get("record_version", 1), "source": r["source"], "date": r["date"].isoformat() if isinstance(r["date"], date) else r["date"], "amount_fils": r.get("amount_fils"), "counterparty": r.get("counterparty"), "account_code": r.get("account_code"), "vat_code": r.get("vat_code"), "currency": r.get("currency"), "invoice_number": r.get("invoice_number"), "description": r.get("description")}


def evidence_hash(rows: list[dict]) -> str:
    """Hash over sorted (record_id, rule-relevant values). Equal hash => no change."""
    keys = ("amount_fils", "date", "counterparty", "account_code", "vat_code", "currency", "invoice_number")
    canon = sorted([[r["record_id"]] + [r.get(k) for k in keys] for r in rows], key=lambda x: x[0])
    return hashlib.sha256(json.dumps(canon, default=str, separators=(",", ":")).encode()).hexdigest()


# --- rules -------------------------------------------------------------------------------------------


def _finding(rule: ExceptionRule, records: list[dict], reason_code: str, flag_type: str, basis: dict) -> dict:
    return {"rule": rule, "anchors": sorted(r["record_id"] for r in records), "rows": [_evidence_row(r) for r in records], "reason_code": reason_code, "flag_type": flag_type, "basis": basis, "severity": rule.default_severity, "amount": max((r.get("amount_fils") or 0) for r in records)}


def _ax01(rule, p, ledger, _bank, _ctx):
    groups: dict[tuple, list] = defaultdict(list)
    for r in ledger:
        if r.get("invoice_number"):
            groups[(_norm_cp(r["counterparty"]), _norm_inv(r["invoice_number"]), r["amount_fils"])].append(r)
    return [_finding(rule, g, "duplicate_invoice_exact", "possible_duplicate", {"amount_match": "exact to the fils"}) for g in groups.values() if len(g) > 1]


def _ax01b(rule, p, ledger, _bank, _ctx):
    out, seen = [], set()
    window = int(p.get("window_days", 7))
    by_key: dict[tuple, list] = defaultdict(list)
    for r in ledger:
        by_key[(_norm_cp(r["counterparty"]), r["amount_fils"], r["direction"])].append(r)
    for rows in by_key.values():
        rows = sorted(rows, key=lambda x: x["date"])
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if (b["date"] - a["date"]).days > window:
                    break
                if _norm_inv(a.get("invoice_number")) == _norm_inv(b.get("invoice_number")):
                    continue  # exact duplicates are AX01
                key = (a["record_id"], b["record_id"])
                if key not in seen and a["counterparty"]:
                    seen.add(key)
                    out.append(_finding(rule, [a, b], "same_counterparty_amount_within_window", "possible_duplicate", {"window_days": window}))
    return out


def _ax02(rule, p, ledger, _bank, ctx):
    out = []
    tol = int(p.get("tolerance_fils_per_line", 100))
    for r in ledger:
        if r.get("vat_fils") is None or not r.get("vat_code"):
            continue
        rate = ctx["vat_rate"](r["vat_code"], r["date"], p)
        if rate is None or rate <= 0:
            continue
        net = r["amount_fils"] - r["vat_fils"]
        expected = round(net * rate / 100)
        if abs(r["vat_fils"] - expected) > tol:
            out.append(_finding(rule, [r], "vat_amount_mismatch", "vat_check", {"tolerance_fils": tol, "rate_percent": rate}))
    return out


def _ax03(rule, p, ledger, _bank, _ctx):
    out = []
    for r in ledger:
        if not r.get("has_trn_field"):
            continue  # unable to assess: the record does not carry the field
        if r.get("vat_code") in ("SR", "RC") and r["amount_fils"] >= int(p.get("gross_threshold_fils", 1_000_000)):
            trn = re.sub(r"\D", "", r.get("trn") or "")
            if len(trn) != int(p.get("trn_digits", 15)):
                out.append(_finding(rule, [r], "trn_missing_or_invalid", "invoice_fields", {"gross_threshold_fils": p.get("gross_threshold_fils"), "trn_digits": p.get("trn_digits")}))
    return out


def _within(a: date, b: date, days: int) -> bool:
    return abs((a - b).days) <= days


def _ax04(rule, p, ledger, bank, ctx):
    out = []
    today = ctx["today"]
    for b in bank:
        if b["amount_fils"] <= int(p.get("min_amount_fils", 500_000)) or (today - b["date"]).days < int(p.get("min_age_days", 14)):
            continue
        win = int(p.get("match_window_days", 5))
        if not any(r["amount_fils"] == b["amount_fils"] and _within(r["date"], b["date"], win) for r in ledger):
            out.append(_finding(rule, [b], "bank_without_ledger", "reconciliation", {"min_amount_fils": p.get("min_amount_fils"), "match_window_days": win, "min_age_days": p.get("min_age_days")}))
    return out


def _ax05(rule, p, ledger, bank, _ctx):
    out = []
    if not bank:
        return out
    lo, hi = min(b["date"] for b in bank), max(b["date"] for b in bank)
    win = int(p.get("match_window_days", 7))
    for r in ledger:
        if r["amount_fils"] <= int(p.get("min_amount_fils", 500_000)) or not (lo <= r["date"] <= hi):
            continue
        if not any(b["amount_fils"] == r["amount_fils"] and _within(r["date"], b["date"], win) for b in bank):
            out.append(_finding(rule, [r], "ledger_without_bank", "reconciliation", {"min_amount_fils": p.get("min_amount_fils"), "match_window_days": win}))
    return out


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _ax06(rule, p, ledger, _bank, _ctx):
    mult, last = int(p.get("multiple_fils", 1_000_000)), int(p.get("last_days_of_period", 2))
    return [_finding(rule, [r], "round_amount_period_edge", "unusual_pattern", {"multiple_fils": mult, "last_days_of_period": last}) for r in ledger if r.get("manual") and r["amount_fils"] and r["amount_fils"] % mult == 0 and (_month_end(r["date"]) - r["date"]).days < last]


def _ax07(rule, p, ledger, _bank, ctx):
    out = []
    ps, pe = ctx["period"]
    for r in ledger:
        posted = r.get("posted_date") or r["date"]
        if r["date"] > posted:
            out.append(_finding(rule, [r], "future_dated", "period_cut_off", {}))
        elif ps <= posted <= pe and not (ps <= r["date"] <= pe):
            out.append(_finding(rule, [r], "dated_outside_period_posted_inside", "period_cut_off", {"period_start": ps.isoformat(), "period_end": pe.isoformat()}))
    return out


def _ax08(rule, p, _ledger, bank, ctx):
    out = []
    if not bank:
        return out
    months = int(p.get("min_history_months", 6))
    first = min(b["date"] for b in bank)
    for b in bank:
        start = b["date"] - timedelta(days=30 * int(p.get("trailing_months", 6)))
        if (b["date"] - first).days < 30 * months:
            continue  # suppressed without 6 months of history
        hist = [x["amount_fils"] for x in bank if start <= x["date"] < b["date"]]
        if not hist:
            continue
        limit = max(int(p.get("floor_fils", 5_000_000)), int(p.get("multiple_of_median", 5)) * median(hist))
        if b["amount_fils"] > limit:
            out.append(_finding(rule, [b], "large_vs_history", "unusual_pattern", {"floor_fils": p.get("floor_fils"), "multiple_of_median": p.get("multiple_of_median")}))
    return out


def _cash(rule, p, ledger, bank, _ctx):
    thr = p.get("threshold_fils")
    if thr is None:  # no value chosen: never fires (no legal cash threshold exists)
        return []
    kws = [k.casefold() for k in p.get("keywords", [])]
    return [_finding(rule, [r], "cash_above_internal_threshold", "internal_review", {"threshold_fils": thr, "label": "internal review threshold, not a legal limit"}) for r in ledger + bank if r["amount_fils"] > int(thr) and any(k in (r.get("description") or "").casefold() for k in kws)]


RULE_FUNCS = {"AX01": _ax01, "AX01b": _ax01b, "AX02": _ax02, "AX03": _ax03, "AX04": _ax04, "AX05": _ax05, "AX06": _ax06, "AX07": _ax07, "AX08": _ax08, CASH_RULE_ID: _cash}


def _vat_rate_fn(db: Session):
    def _rate(code: str, on: date, p: dict) -> float | None:
        try:
            from app.modules.bookkeeping.service import vat_code_for

            vc = vat_code_for(db, code, on)
            if vc is not None:
                return float(vc.rate_percent)
        except ImportError:  # pragma: no cover
            pass
        return float(p.get("default_rate_percent", 5)) if code in ("SR", "RC") else None

    return _rate


# --- review cycle ------------------------------------------------------------------------------------


def default_period(db: Session, company_id: str, today: date | None = None) -> tuple[date, date, str]:
    from app.modules.companies.models import Company

    co = db.get(Company, company_id)
    m, d = (co.financial_year_end_month, co.financial_year_end_day) if co else (12, 31)
    today = today or date.today()
    end = date(today.year, m, d)
    if end < today:
        end = date(today.year + 1, m, d)
    start = date(end.year - 1, m, d) + timedelta(days=1)
    return start, end, f"FY{end.year}"


def bank_rules_visible(db: Session, company_id: str) -> bool:
    return bool(source_gate(db, company_id, "bank").get("allowed"))


def run_review_cycle(db: Session, company_id: str, *, actor_key: str | None = None, today: date | None = None, period: tuple[date, date, str] | None = None) -> ReviewCycle:
    """Read consented sources in gated batches, evaluate the versioned rules, create or revise flags."""
    today = today or date.today()
    ps, pe, pid = period or default_period(db, company_id, today)
    cyc = ReviewCycle(company_id=company_id, period_start=ps, period_end=pe, model_version=model_version())
    db.add(cyc)
    db.flush()
    batch_n = _int(db, "auditagent.consent_gate.batch_max_records", 100)
    read: dict[str, list[dict]] = {"ledger": [], "bank": []}
    for source, loader in (("ledger", ledger_records), ("bank", bank_records)):
        gate = source_gate(db, company_id, source, actor_key=actor_key)
        if not gate.get("allowed"):
            cyc.sources_refused = {**cyc.sources_refused, source: gate.get("state") or "awaiting_consent"}
            if gate.get("state") in ("withdrawn", "expired"):
                mask_source(db, company_id, source, ended_on=gate.get("ended_on"))
            continue
        records = loader(db, company_id)
        kept: list[dict] = []
        cancelled = False
        for i in range(0, len(records), batch_n):
            batch = records[i:i + batch_n]
            if BATCH_HOOK is not None:
                BATCH_HOOK(db, company_id, source, i // batch_n)
            # Consent gate before each page/batch; a batch is saved only if its save completed before withdrawal.
            if not source_gate(db, company_id, source, actor_key=actor_key).get("allowed"):
                cancelled = True
                cyc.batches_discarded += 1
                break
            kept.extend(batch)
            cyc.batches_saved += 1
        if cancelled:
            cyc.status, cyc.cancelled_at, cyc.cancel_reason = "cancelled_on_withdrawal", utcnow(), f"{source}_consent_withdrawn"
            cyc.sources_refused = {**cyc.sources_refused, source: "withdrawn"}
            mask_source(db, company_id, source, ended_on=None)
            record_event(db, event_type="CYCLE_CANCELLED_ON_WITHDRAWAL", category="agent", outcome="cancelled", reason_code="CONSENT_WITHDRAWN", actor_key=actor_key, company_id=company_id, subject_type="review_cycle", subject_id=cyc.id, details={"source": source, "batches_saved": cyc.batches_saved})
            continue  # in-flight reads for this source are discarded entirely; never re-read
        read[source] = kept
        cyc.sources_read = sorted(set(cyc.sources_read) | {source})
        cyc.records_read += len(kept)
    if not cyc.sources_read:
        cyc.status = "refused_no_source" if cyc.status == "completed" else cyc.status
        cyc.finished_at = utcnow()
        record_event(db, event_type="EVALUATION_RECORDED", category="agent", outcome="refused", reason_code="NO_SOURCE_CONSENTED", actor_key=actor_key, company_id=company_id, subject_type="review_cycle", subject_id=cyc.id, details={"sources_refused": cyc.sources_refused, "model_version": cyc.model_version})
        return cyc
    ctx = {"today": today, "period": (ps, pe), "vat_rate": _vat_rate_fn(db)}
    findings: list[dict] = []
    versions: dict[str, str] = {}
    unable: dict[str, int] = {}
    for rule in current_rules(db):
        enabled, params = effective_rule(db, company_id, rule)
        if not enabled:
            continue
        if rule.bank_dependent and "bank" not in cyc.sources_read:
            continue  # hidden for companies without active bank consent
        fn = RULE_FUNCS.get(rule.rule_id)
        if fn is None:
            continue
        versions[rule.rule_id] = rule.rule_version
        if rule.rule_id == "AX03":
            unable["AX03"] = sum(1 for r in read["ledger"] if not r.get("has_trn_field"))
        findings.extend(fn(rule, params, read["ledger"], read["bank"], ctx))
    cyc.rule_versions, cyc.unable_to_assess = versions, unable
    cyc.source_refs = sorted({r["record_id"] for rs in read.values() for r in rs})[:500]
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), -f["amount"]))
    first_backfill = db.scalar(select(ExceptionFlag.id).where(ExceptionFlag.company_id == company_id, ExceptionFlag.is_demo.is_(False)).limit(1)) is None
    cap = _int(db, "auditagent.backfill.first_cap_per_company", 100)
    if first_backfill and len(findings) > cap:
        findings, cyc.more_available = findings[:cap], True
    upto = max((r["date"] for rs in read.values() for r in rs), default=None)
    for f in findings:
        created, revised = upsert_flag(db, company_id, pid, f, based_on=upto, cycle_id=cyc.id)
        cyc.flags_created += int(created)
        cyc.revisions_created += int(revised)
    cyc.finished_at = utcnow()
    record_event(db, event_type="EVALUATION_RECORDED", category="agent", actor_key=actor_key, company_id=company_id, subject_type="review_cycle", subject_id=cyc.id, details={"sources": cyc.sources_read, "records": cyc.records_read, "rule_versions": versions, "model_version": cyc.model_version, "flags_created": cyc.flags_created, "revisions": cyc.revisions_created, "status": cyc.status})
    db.flush()
    return cyc


def _current_revision(db: Session, flag: ExceptionFlag) -> FlagRevision:
    return db.scalar(select(FlagRevision).where(FlagRevision.flag_id == flag.id, FlagRevision.revision_no == flag.current_revision_no))


def _active_decision(db: Session, flag_id: str, revision_no: int | None = None) -> FlagDecision | None:
    stmt = select(FlagDecision).where(FlagDecision.flag_id == flag_id, FlagDecision.superseded_by.is_(None), FlagDecision.quarantined.is_(False))
    if revision_no is not None:
        stmt = stmt.where(FlagDecision.revision_no == revision_no)
    return db.scalar(stmt.order_by(FlagDecision.decided_at.desc()))


def upsert_flag(db: Session, company_id: str, period: str, f: dict, *, based_on: date | None = None, cycle_id: str | None = None, is_demo: bool = False) -> tuple[bool, bool]:
    """Lineage: shared anchor => same flag. Material change => new revision (status back to New, decision kept).
    Equal evidence hash => nothing written."""
    rule: ExceptionRule = f["rule"]
    ev_hash = evidence_hash(f["rows"])
    anchors = set(f["anchors"])
    existing = None
    for fl in db.scalars(select(ExceptionFlag).where(ExceptionFlag.company_id == company_id, ExceptionFlag.rule_id == rule.rule_id, ExceptionFlag.period == period)):
        if anchors & set(fl.anchor_record_ids or []):
            existing = fl
            break
    now = utcnow()
    if existing is None:
        fl = ExceptionFlag(company_id=company_id, rule_id=rule.rule_id, rule_version=rule.rule_version, period=period, anchor_record_ids=sorted(anchors), source=f["rows"][0]["source"] if f["rows"] else "ledger", severity=f["severity"], based_on_data_up_to=based_on, is_demo=is_demo)
        db.add(fl)
        db.flush()
        db.add(FlagRevision(flag_id=fl.id, revision_no=1, change_summary="Item raised for review", rule_id=rule.rule_id, rule_version=rule.rule_version, severity=f["severity"], flag_type=f["flag_type"], reason_code=f["reason_code"], evidence_set=[{"record_id": r["record_id"], "record_version": r["record_version"]} for r in f["rows"]], evidence_rows=f["rows"], basis=f.get("basis"), evidence_hash=ev_hash, model_version=model_version()))
        db.flush()
        record_event(db, event_type="FLAG_CREATED", category="agent", company_id=company_id, subject_type="exception_flag", subject_id=fl.id, details={"rule_id": rule.rule_id, "rule_version": rule.rule_version, "severity": f["severity"], "records": len(f["rows"]), "cycle_id": cycle_id})
        return True, False
    cur = _current_revision(db, existing)
    if cur.evidence_hash == ev_hash:
        return False, False  # identical re-sync or rule version change with the same outcome: nothing written
    decision = _active_decision(db, existing.id, cur.revision_no)
    if decision is None:
        cur.superseded_before_decision = True  # not counted in K16
    n = existing.current_revision_no + 1
    db.add(FlagRevision(flag_id=existing.id, revision_no=n, change_summary="Evidence changed: records or rule-relevant fields differ", rule_id=rule.rule_id, rule_version=rule.rule_version, severity=f["severity"], flag_type=f["flag_type"], reason_code=f["reason_code"], evidence_set=[{"record_id": r["record_id"], "record_version": r["record_version"]} for r in f["rows"]], evidence_rows=f["rows"], basis=f.get("basis"), evidence_hash=ev_hash, model_version=model_version()))
    existing.current_revision_no = n
    existing.anchor_record_ids = sorted(set(existing.anchor_record_ids or []) | anchors)
    existing.status, existing.human_review_status, existing.severity, existing.updated_at = "New", "pending", f["severity"], now
    if decision is not None:
        existing.evidence_changed_since = decision.decided_at
    existing.based_on_data_up_to = based_on or existing.based_on_data_up_to
    db.flush()
    record_event(db, event_type="FLAG_REVISION_CREATED", category="agent", company_id=company_id, subject_type="exception_flag", subject_id=existing.id, details={"revision_no": n, "rule_version": rule.rule_version, "prior_decision_kept": decision is not None})
    return False, True


# --- withdrawal: masking and deletion ---------------------------------------------------------------------


def mask_source(db: Session, company_id: str, source: str, *, ended_on: str | None = None) -> int:
    """Masking is immediate; stored copies are deleted on the consent-store schedule (assumed 24 h)."""
    hours = _int(db, "auditagent.consent_store.deletion_schedule_hours", 24)
    n = 0
    now = utcnow()
    for fl in db.scalars(select(ExceptionFlag).where(ExceptionFlag.company_id == company_id, ExceptionFlag.source == source, ExceptionFlag.source_withdrawn.is_(False))):
        fl.source_withdrawn, fl.withdrawn_at = True, now
        for rev in db.scalars(select(FlagRevision).where(FlagRevision.flag_id == fl.id)):
            rev.masked = True
        db.add(EvidenceMask(flag_id=fl.id, source=source, masked_at=now, deletion_due_at=now + timedelta(hours=hours)))
        n += 1
    if n:
        record_event(db, event_type="SOURCE_WITHDRAWN_MASKED", category="consent", company_id=company_id, details={"source": source, "flags": n, "ended_on": ended_on})
    db.flush()
    return n


def run_evidence_deletion(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    n = 0
    for m in db.scalars(select(EvidenceMask).where(EvidenceMask.deleted_at.is_(None), EvidenceMask.deletion_due_at <= now)):
        for rev in db.scalars(select(FlagRevision).where(FlagRevision.flag_id == m.flag_id)):
            rev.evidence_rows = [{"record_id": r.get("record_id"), "record_version": r.get("record_version"), "source": r.get("source"), "date": r.get("date")} for r in rev.evidence_rows or []]
        m.deleted_at = now
        n += 1
        record_event(db, event_type="EVIDENCE_DELETED", category="consent", subject_type="exception_flag", subject_id=m.flag_id, details={"source": m.source})
    db.flush()
    return n


# --- decisions ---------------------------------------------------------------------------------------


def get_flag(db: Session, company_id: str, flag_id: str) -> ExceptionFlag:
    fl = db.get(ExceptionFlag, flag_id)
    if fl is None or fl.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    return fl


def decide(db: Session, flag: ExceptionFlag, *, decision: str, reason: str, decided_by_uuid: str | None, decided_by_name: str, actor_role: str, role_label: str | None, actor_key: str | None, engagement_id: str | None = None, reason_code: str | None = None) -> FlagDecision:
    if decision not in DECISIONS:
        raise ValidationFailed("decision must be confirm, explain or dismiss", reason_code="DECISION_INVALID")
    min_chars = _int(db, "auditagent.decision.reason_min_chars", 10)
    if len((reason or "").strip()) < min_chars:
        raise ValidationFailed(f"a reason of at least {min_chars} characters is required", reason_code="REASON_TOO_SHORT", details={"min_chars": min_chars})
    rev = _current_revision(db, flag)
    prior = _active_decision(db, flag.id, rev.revision_no)
    now = utcnow()
    d = FlagDecision(flag_id=flag.id, revision_no=rev.revision_no, decision=decision, reason=reason.strip(), reason_code=reason_code, decided_by_uuid=decided_by_uuid, decided_by_name=decided_by_name, actor_role=actor_role, role_label=role_label, decided_at=now, decision_month=to_dubai(now).strftime("%Y-%m"), rule_id=rev.rule_id, rule_version=rev.rule_version, severity=rev.severity, engagement_id=engagement_id)
    db.add(d)
    db.flush()
    if prior is not None:
        prior.superseded_by = d.id  # a changed decision on the same revision replaces the earlier K16 count
    flag.status, flag.human_review_status, flag.evidence_changed_since, flag.updated_at = DECISION_TO_STATUS[decision], {"confirm": "confirmed", "explain": "explained", "dismiss": "dismissed"}[decision], None, now
    rev.status = flag.human_review_status
    db.flush()
    record_event(db, event_type="DECISION_CHANGED" if prior else "DECISION_RECORDED", category="agent", actor_key=actor_key, actor_role=actor_role, company_id=flag.company_id, subject_type="exception_flag", subject_id=flag.id, details={"decision": decision, "revision_no": rev.revision_no, "rule_id": rev.rule_id, "rule_version": rev.rule_version, "engagement_id": engagement_id})
    return d


def escalate_flag(db: Session, flag: ExceptionFlag, *, actor_key: str | None, actor_role: str) -> ExceptionFlag:
    try:
        from app.modules.escalation.service import open_case

        case = open_case(db, company_id=flag.company_id, module="audit", reason_code="user_requested", matter_key=f"audit_flag|{flag.id}", event_id=f"flag-escalate-{flag.id}-{flag.current_revision_no}", opened_by=actor_role, opened_by_key=actor_key, linked_item_id=flag.id, trigger_source="audit_exception")
        flag.escalation_case_id = case.case_id
    except ImportError:  # pragma: no cover
        pass
    flag.status = "Escalated"
    record_event(db, event_type="FLAG_ESCALATED", category="escalation", actor_key=actor_key, actor_role=actor_role, company_id=flag.company_id, subject_type="exception_flag", subject_id=flag.id, details={"case_id": flag.escalation_case_id})
    db.flush()
    return flag


def quarantine_decisions(db: Session, company_id: str, identity_uuid: str) -> int:
    """Decisions saved by a delegate whose rights were removed: 'Quarantined, awaiting owner review'."""
    n = 0
    for d in db.scalars(select(FlagDecision).join(ExceptionFlag, ExceptionFlag.id == FlagDecision.flag_id).where(ExceptionFlag.company_id == company_id, FlagDecision.decided_by_uuid == identity_uuid, FlagDecision.superseded_by.is_(None), FlagDecision.actor_role == "delegate")):
        d.quarantined = True
        n += 1
    if n:
        record_event(db, event_type="QUARANTINED_DECISION", category="agent", company_id=company_id, details={"decisions": n})
    db.flush()
    return n


def k16(db: Session, company_id: str | None = None) -> list[dict]:
    """K16 = confirmed / (confirmed + dismissed) per rule_id, rule_version, severity and decision month."""
    stmt = select(FlagDecision).where(FlagDecision.superseded_by.is_(None), FlagDecision.quarantined.is_(False), FlagDecision.decision.in_(("confirm", "dismiss")))
    if company_id:
        stmt = stmt.join(ExceptionFlag, ExceptionFlag.id == FlagDecision.flag_id).where(ExceptionFlag.company_id == company_id)
    cells: dict[tuple, dict] = {}
    for d in db.scalars(stmt):
        key = (d.rule_id, d.rule_version, d.severity, d.decision_month)
        c = cells.setdefault(key, {"rule_id": d.rule_id, "rule_version": d.rule_version, "severity": d.severity, "month": d.decision_month, "confirmed": 0, "dismissed": 0})
        c["confirmed" if d.decision == "confirm" else "dismissed"] += 1
    out = []
    for c in cells.values():
        tot = c["confirmed"] + c["dismissed"]
        out.append({**c, "precision": round(c["confirmed"] / tot, 4) if tot else None})
    return sorted(out, key=lambda x: (x["rule_id"], x["rule_version"], x["month"]))


def k16_by_rule_version(db: Session, company_id: str | None = None) -> dict[tuple[str, str], float | None]:
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in k16(db, company_id):
        agg[(r["rule_id"], r["rule_version"])][0] += r["confirmed"]
        agg[(r["rule_id"], r["rule_version"])][1] += r["dismissed"]
    return {k: (v[0] / (v[0] + v[1]) if (v[0] + v[1]) else None) for k, v in agg.items()}


# --- serialisation -----------------------------------------------------------------------------------------


def _mask_row(r: dict) -> dict:
    return {"record_id": r.get("record_id"), "record_version": r.get("record_version"), "source": r.get("source"), "date": r.get("date"), "masked": True}


def flag_dict(db: Session, fl: ExceptionFlag, *, detail: bool = True) -> dict:
    rev = _current_revision(db, fl)
    rule = db.scalar(select(ExceptionRule).where(ExceptionRule.rule_id == fl.rule_id, ExceptionRule.rule_version == rev.rule_version)) if rev else None
    decisions = list(db.scalars(select(FlagDecision).where(FlagDecision.flag_id == fl.id).order_by(FlagDecision.decided_at.desc())))
    active = next((d for d in decisions if d.superseded_by is None and not d.quarantined), None)
    out = {
        "id": fl.id, "rule_id": fl.rule_id, "rule_version_at_flag": fl.rule_version, "rule_version": rev.rule_version if rev else fl.rule_version,
        "rule_title": {"en": rule.title_en, "ar": rule.title_ar} if rule else None, "legal_anchor": rule.legal_anchor if rule else None,
        "rule_label": rule.label if rule and rule.rule_id == CASH_RULE_ID else None,
        "period": fl.period, "source": fl.source, "severity": fl.severity, "status": fl.status, "human_review_status": fl.human_review_status,
        "flag_type": rev.flag_type if rev else None, "reason_code": rev.reason_code if rev else None, "revision_no": fl.current_revision_no,
        "flagged_at": fl.flagged_at.isoformat(), "updated_at": fl.updated_at.isoformat(), "evidence_changed_since": fl.evidence_changed_since.isoformat() if fl.evidence_changed_since else None,
        "source_withdrawn": fl.source_withdrawn, "withdrawn_at": fl.withdrawn_at.isoformat() if fl.withdrawn_at else None, "based_on_data_up_to": fl.based_on_data_up_to.isoformat() if fl.based_on_data_up_to else None,
        "ai_label": {"en": "AI-generated, reviewed by " + active.decided_by_name, "ar": "أُنشئ بالذكاء الاصطناعي، راجعه " + active.decided_by_name} if active else {"en": "AI-generated, pending human review", "ar": "أُنشئ بالذكاء الاصطناعي، بانتظار المراجعة البشرية"},
        "escalation_case_id": fl.escalation_case_id, "is_demo": fl.is_demo, "row_count": len(rev.evidence_rows or []) if rev else 0,
        "amount_fils": None if fl.source_withdrawn else max((r.get("amount_fils") or 0 for r in (rev.evidence_rows or [])), default=None) if rev else None,
    }
    if detail and rev:
        rows = rev.evidence_rows or []
        out["evidence"] = [_mask_row(r) for r in rows] if fl.source_withdrawn else rows
        out["basis"] = rev.basis
        out["model_version"] = rev.model_version
        out["revisions"] = [{"revision_no": r.revision_no, "created_at": r.created_at.isoformat(), "actor": r.actor, "change_summary": r.change_summary, "rule_version": r.rule_version, "superseded_before_decision": r.superseded_before_decision, "evidence": [_mask_row(x) for x in r.evidence_rows or []] if fl.source_withdrawn else r.evidence_rows} for r in db.scalars(select(FlagRevision).where(FlagRevision.flag_id == fl.id).order_by(FlagRevision.revision_no.desc()))]
        out["decisions"] = [{"id": d.id, "decision": d.decision, "reason": d.reason, "by": d.decided_by_name, "role": d.actor_role, "role_label": d.role_label, "at": d.decided_at.isoformat(), "revision_no": d.revision_no, "superseded": d.superseded_by is not None, "quarantined": d.quarantined, "engagement_id": d.engagement_id} for d in decisions]
    return out


def list_flags(db: Session, company_id: str, *, include_bank: bool | None = None, audit_file_id: str | None = None) -> list[ExceptionFlag]:
    stmt = select(ExceptionFlag).where(ExceptionFlag.company_id == company_id)
    if audit_file_id:
        stmt = stmt.where(ExceptionFlag.audit_file_id == audit_file_id)
    flags = list(db.scalars(stmt.order_by(ExceptionFlag.flagged_at.desc())))
    if include_bank is False:
        bank_rules = {r.rule_id for r in current_rules(db) if r.bank_dependent}
        flags = [f for f in flags if f.rule_id not in bank_rules]
    return flags


def last_cycle(db: Session, company_id: str) -> ReviewCycle | None:
    return db.scalar(select(ReviewCycle).where(ReviewCycle.company_id == company_id).order_by(ReviewCycle.started_at.desc()).limit(1))


def require_decide_right(principal: Any, company_id: str, *, has_engagement: bool, staff_prepare: bool) -> tuple[str, str | None]:
    """Owner (UAE), delegate with the audit function, assigned licensed auditor or Qeonix audit operations may decide."""
    roles = principal.roles_for(company_id) if hasattr(principal, "roles_for") else []
    for r in roles:
        if r.role == "owner":
            return "owner", None
        if r.role == "delegate" and ("audit" in (r.functions or []) or "all" in (r.functions or [])):
            return "delegate", f"Delegate for {company_id}"
    if has_engagement:
        return "licensed_auditor", "Licensed auditor (assigned engagement)"
    if staff_prepare:
        return "qeonix_audit_ops", "Qeonix audit operations"
    if any(r.role == "delegate" for r in roles):
        raise Forbidden("You can view this flag. Ask the owner to give you the right to decide.", reason_code="NO_DECIDE_RIGHT")
    raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION")
