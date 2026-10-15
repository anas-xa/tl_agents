"""Draft pack service (E5-S3): assembly, pack_hash/get_pack for approvals (E6-S1), role-bound status
transitions, quarantine hold, export, retention classes. The platform prepares; it never files.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as bk
from app.modules.config.service import get_config
from app.modules.drafts.models import (
    DRAFT_STATUSES,
    EMARATAX_SENTENCE,
    PRODUCT_NAME,
    STATUS_LABELS,
    SYSTEM_ONLY_STATUSES,
    WATERMARK,
    DraftExport,
    DraftPack,
    DraftStatusHistory,
)
from app.modules.tax import service as tax

BANNED_TERMS = ("audit certificate", "audit report", "certified", "Compliant", "PDPL-compliant", "independent", "Filed", "penalty applies", "Tax Agent", "Included with your licence", "hosted in the UAE", "your data is deleted", "verified")
REASON_RUBRIC_DEFAULT = ["figure_corrected", "source_added_or_changed", "period_or_date_change", "wording_only", "data_refresh", "other"]
RETENTION_CLASSES_DEFAULT = {
    "1": {"name": "superseded drafts and intermediate versions", "rule": "purged on a schedule unless linked to a final report or approval", "status": "to_be_confirmed"},
    "2": {"name": "source traces", "rule": "purged on a schedule unless linked to a final report or approval", "status": "to_be_confirmed"},
    "3": {"name": "export and access logs", "rule": "follow DET/DESC security requirements; personal data needs a purpose and purge rule", "status": "to_be_confirmed"},
    "4": {"name": "final prepared reports the owner approved or filed", "rule": "legal hold", "status": "to_be_confirmed"},
    "5": {"name": "approval records", "rule": "legal hold", "status": "to_be_confirmed"},
}
TERMS = {
    "output_vat": {"en": "Output VAT", "ar": "ضريبة المخرجات", "gloss_en": "VAT you charged on sales", "gloss_ar": "الضريبة التي فرضتها على مبيعاتك"},
    "input_vat": {"en": "Input VAT", "ar": "ضريبة المدخلات", "gloss_en": "VAT you paid on purchases that you can recover", "gloss_ar": "الضريبة التي دفعتها على المشتريات ويمكنك استردادها"},
    "net_vat": {"en": "Net VAT payable or refundable", "ar": "صافي الضريبة المستحقة أو القابلة للاسترداد", "gloss_en": "Output VAT minus input VAT", "gloss_ar": "ضريبة المخرجات ناقص ضريبة المدخلات"},
    "accounting_profit": {"en": "Accounting profit", "ar": "الربح المحاسبي", "gloss_en": "Income minus expenses from the books", "gloss_ar": "الإيرادات ناقص المصروفات من الدفاتر"},
    "taxable_income": {"en": "Taxable income", "ar": "الدخل الخاضع للضريبة", "gloss_en": "Accounting profit after adjustments", "gloss_ar": "الربح المحاسبي بعد التعديلات"},
    "tax": {"en": "Corporate tax", "ar": "ضريبة الشركات", "gloss_en": "9% above the AED 375,000 threshold (conditional calculation)", "gloss_ar": "9% فوق حد 375,000 درهم (احتساب مشروط)"},
    "sbr": {"en": "Small Business Relief indicator", "ar": "مؤشر إعفاء الأعمال الصغيرة", "gloss_en": "Eligibility indicator only; the election is made in the return", "gloss_ar": "مؤشر أهلية فقط؛ يتم الاختيار في الإقرار"},
    "adjustment": {"en": "Adjustment", "ar": "تعديل", "gloss_en": "An item not in the books, entered by a person with a reason", "gloss_ar": "بند غير مدرج في الدفاتر أدخله شخص مع ذكر السبب"},
    "loss_cf": {"en": "Loss carry-forward applied", "ar": "الخسائر المرحّلة المطبّقة", "gloss_en": "Earlier losses set against this period, capped at 75%", "gloss_ar": "خسائر سابقة تُخصم من هذه الفترة بحد أقصى 75%"},
}


def check_banned(text: str) -> list[str]:
    """Banned terms in unsigned outputs (titles, watermarks, labels, file names)."""
    found = []
    for t in BANNED_TERMS:
        pat = re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE if t[0].islower() else 0)
        if pat.search(text):
            if t == "Filed" and "Filed (user-confirmed)" in text:
                continue
            found.append(t)
    return found


# --- pack assembly -------------------------------------------------------------------------------


def _figure(key: str, value_fils: int | None, line_class: str, sources: list[dict], *, text: str | None = None, box_ref: str | None = None, no_source_reason: str | None = None, extra: dict | None = None) -> dict:
    term = TERMS.get(key.split(":")[0], {"en": key, "ar": key, "gloss_en": "", "gloss_ar": ""})
    return {"key": key, "term": {"en": term["en"], "ar": term["ar"]}, "gloss": {"en": term["gloss_en"], "ar": term["gloss_ar"]}, "value_fils": value_fils, "text": text, "line_class": line_class, "source_refs": sources, "no_source": not sources and line_class != "person_entered", "no_source_reason": no_source_reason, "return_box_ref": box_ref, "accessible_name": f"{term['en']}, AED {(value_fils or 0) / 100:,.2f}, {'no source' if not sources else 'source available'}, opens details", **(extra or {})}


def _lines_for(calc: Any) -> tuple[list[dict], list[dict], dict]:
    o = calc.outputs or {}
    sources: list[dict] = []
    if calc.tax_type == "vat":
        for ln in o.get("lines", []):
            for s in ln["source_documents"]:
                sources.append({**s, "classification_id": ln["classification_id"], "tax_point_date": ln["tax_point_date"], "tax_point_rule": ln["tax_point_rule"], "vat_code": ln["vat_code"], "fx": ln.get("fx")})
        src_out = [{"classification_id": ln["classification_id"], "source_id": ln["source_documents"][0]["source_id"]} for ln in o.get("lines", []) if ln["side"] == "output"]
        src_in = [{"classification_id": ln["classification_id"], "source_id": ln["source_documents"][0]["source_id"]} for ln in o.get("lines", []) if ln["side"] == "input"]
        lines = [
            _figure("output_vat", o.get("output_vat_fils"), "calculated", src_out, box_ref="1a"),
            _figure("input_vat", o.get("input_vat_fils"), "calculated", src_in, box_ref="9"),
            _figure("net_vat", o.get("net_vat_fils"), "calculated", src_out + src_in, box_ref="12/13/14"),
        ]
        basis = {"rule_refs": calc.rule_refs, "formula": "net VAT = output VAT - input VAT; VAT per line = net x rate (or gross x rate/(100+rate) for bank lines)", "vat_code_list": "vat-codes-v1 (configured, pending FTA confirmation)", "box_mapping": "configured, pending FTA confirmation", "fx_source": "CBUAE rate on the tax-point date (configured, pending FTA confirmation)", "rounding": o.get("rounding")}
        return lines, sources, basis
    books = o.get("books") or {}
    prof_src = [{"source": "books", "confirmed_transactions": books.get("confirmed_transactions", 0)}] if o.get("accounting_profit_source") == "classified" else []
    lines = [_figure("accounting_profit", o.get("accounting_profit_fils"), "calculated" if prof_src else "person_entered", prof_src, extra={"entered_by": None if prof_src else "owner (person-entered)"})]
    for a in o.get("adjustments", []):
        lines.append(_figure(f"adjustment:{a['kind']}", a["amount_fils"], a["class"], [], text=a.get("label"), extra={"entered_by": a.get("entered_by"), "review_status": a.get("review_status"), "held_for_specialist": a.get("held_for_specialist"), "reason": a.get("reason")}))
    lcf = o.get("loss_carry_forward") or {}
    if lcf.get("applied_fils"):
        lines.append(_figure("loss_cf", -int(lcf["applied_fils"]), "calculated", [{"source": "person-entered opening balance"}]))
    lines.append(_figure("taxable_income", o.get("taxable_income_fils"), "calculated", [{"source": "calculated from the lines above"}]))
    sbr = o.get("sbr") or {}
    lines.append(_figure("sbr", None, "calculated", [{"source": sbr.get("revenue_source") or "owner to confirm"}], text=f"{sbr.get('indicator')}: {sbr.get('text')}", extra={"sbr": {k: sbr.get(k) for k in ("indicator", "text", "reason", "revenue_fils", "revenue_source", "cutoff_date", "election_status", "election_allowed", "instrument", "rule", "review_status", "tax_if_elected_fils", "tax_if_not_elected_fils")}}))
    lines.append(_figure("tax", o.get("tax_fils"), "calculated", [{"source": "calculated"}]))
    basis = {"rule_refs": calc.rule_refs, "formula": "taxable income = accounting profit + adjustments - loss carry-forward (cap 75%); tax = 9% x max(0, taxable income - AED 375,000)", "sbr": "indicator only; election in the return", "rounding": {"display_decimals": 2, "label": "display default only, provisional"}}
    sources = [{"source": "books (confirmed entries)", "count": books.get("confirmed_transactions", 0)}]
    return lines, sources, basis


def data_version_for(calc: Any) -> str:
    return hashlib.sha256(f"{calc.id}|{calc.version}|{calc.data_hash}|{calc.rule_version}".encode()).hexdigest()[:16]


def pack_hash(pack: DraftPack | dict) -> str:
    """Content hash an approval binds to: one version only, never carried over (E6-S1 hook)."""
    d = pack if isinstance(pack, dict) else {"id": pack.id, "company_id": pack.company_id, "tax_type": pack.tax_type, "period_id": pack.period_id, "version": pack.version, "data_version": pack.data_version, "rule_version": pack.rule_version, "lines": pack.lines, "assumptions": pack.assumptions}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def get_pack(db: Session, pack_id: str) -> DraftPack:
    p = db.get(DraftPack, pack_id)
    if p is None:
        raise NotFound("draft not found", reason_code="NOT_FOUND")
    return p


def latest_pack(db: Session, company_id: str, tax_type: str, period_id: str) -> DraftPack | None:
    return db.scalar(select(DraftPack).where(DraftPack.company_id == company_id, DraftPack.tax_type == tax_type, DraftPack.period_id == period_id).order_by(DraftPack.version.desc()).limit(1))


def _history(db: Session, pack: DraftPack, to_status: str, *, actor: Any | None, role: str | None, system: bool, reason_code: str | None = None, reason_text: str | None = None, changed_fields: list[str] | None = None) -> None:
    from_status = pack.review_status
    pack.review_status = to_status
    db.add(DraftStatusHistory(pack_id=pack.id, from_status=from_status, to_status=to_status, actor_uuid=getattr(actor, "identity_uuid", None), actor_name=getattr(actor, "display_name", None), actor_role=role, system=system, reason_code=reason_code, reason_text=reason_text, changed_fields=changed_fields, material=bk.is_material(changed_fields) if changed_fields else None))
    record_event(db, event_type="DRAFT_STATUS_CHANGED", category="agent" if system else "sign_off", actor_key=getattr(actor, "actor_key", None), actor_role=role or ("system" if system else None), company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id, details={"from": from_status, "to": to_status, "system": system, "reason_code": reason_code, "version": pack.version})


def create_pack(db: Session, company_id: str, tax_type: str, period_id: str, *, actor: Any | None = None, run_calculation: bool = True, what_changed: str | None = None, is_demo: bool = False) -> DraftPack:
    """Assemble a versioned draft once the completeness check passes. Earlier versions become Superseded (system)."""
    actor_key = getattr(actor, "actor_key", None)
    if tax_type == "ct" and tax.get_profile(db, company_id).ct_status != "standalone_mainland":
        calc = tax.calculate_ct(db, company_id, period_id, actor=actor)  # blocked + escalated (Q96), reported first
        record_event(db, event_type="DRAFT_GENERATION_FAILED", category="agent", outcome="failed", reason_code="BLOCKED", actor_key=actor_key, company_id=company_id, subject_type="period", subject_id=period_id, details={"calculation_id": calc.id})
        raise ValidationFailed(f"Draft could not be prepared. Cause: {calc.state_reason}. Next step: a specialist will contact you.", reason_code="GENERATION_FAILED", details={"cause": calc.state_reason, "next_step": "a specialist will contact you", "state": calc.state})
    facts = tax.completeness_facts(db, company_id, tax_type)
    prev_calc = tax.latest(db, company_id, tax_type, period_id)
    if tax_type == "ct" and prev_calc and prev_calc.outputs and prev_calc.outputs.get("accounting_profit_source") == "company-entered":
        facts |= {"transactions": True, "all_reviewed": True}
    check = bk.evaluate_completeness(db, company_id, tax_type, period_id, facts=facts)
    if not check.passed:
        record_event(db, event_type="COMPLETENESS_CHECK_FAILED", category="agent", outcome="incomplete", actor_key=actor_key, company_id=company_id, subject_type="period", subject_id=period_id, details={"missing": [m["key"] for m in check.missing_items]})
        raise ValidationFailed(f"We cannot prepare this draft yet. {len(check.missing_items)} items are missing.", reason_code="DATA_INCOMPLETE", details={"missing_items": check.missing_items, "version": check.version})
    if run_calculation or prev_calc is None:
        if tax_type == "vat":
            calc = tax.calculate_vat(db, company_id, period_id, actor=actor)
        else:
            inputs = prev_calc.inputs if prev_calc and prev_calc.inputs else {}
            calc = tax.calculate_ct(db, company_id, period_id, actor=actor, accounting_profit_fils=inputs.get("accounting_profit_fils") if prev_calc and prev_calc.outputs and prev_calc.outputs.get("accounting_profit_source") == "company-entered" else None, revenue_fils=inputs.get("revenue_fils"), loss_cf_fils=inputs.get("loss_cf_fils"))
    else:
        calc = prev_calc
        tax.check_stale(db, calc)
    if calc.state in ("blocked", "no_rule_stop", "missing_vat_code", "run_failed"):
        cause = {"blocked": calc.state_reason, "no_rule_stop": "the rules for this period are not loaded", "missing_vat_code": calc.state_reason, "run_failed": "the calculation did not finish"}[calc.state]
        step = {"blocked": "a specialist will contact you", "no_rule_stop": "a specialist has been notified", "missing_vat_code": "review the transactions, then recalculate", "run_failed": "try again or ask a human"}[calc.state]
        record_event(db, event_type="DRAFT_GENERATION_FAILED", category="agent", outcome="failed", reason_code=calc.state.upper(), actor_key=actor_key, company_id=company_id, subject_type="period", subject_id=period_id, details={"calculation_id": calc.id})
        raise ValidationFailed(f"Draft could not be prepared. Cause: {cause}. Next step: {step}.", reason_code="GENERATION_FAILED", details={"cause": cause, "next_step": step, "state": calc.state})
    lines, sources, basis = _lines_for(calc)
    prev = latest_pack(db, company_id, tax_type, period_id)
    pack = DraftPack(
        company_id=company_id,
        tax_type=tax_type,
        period_id=period_id,
        version=(prev.version + 1) if prev else 1,
        data_version=data_version_for(calc),
        rule_version=calc.rule_version,
        calculation_id=calc.id,
        assumptions=[{"text": "Figures are estimates until the instruments are verified.", "citation": "Q93/Q99"}, {"text": "VAT codes, box mapping and FX source are configured, pending FTA confirmation.", "citation": "Q86"}, *([{"text": f"Rules used: {calc.rule_version}", "citation": "rule register (E3-S2)"}] if calc.rule_version else []), *([{"text": f"Excludes {calc.excluded_count} items that need review.", "citation": "E5-S2 incomplete state"}] if calc.excluded_count else [])],
        lines=lines,
        ai_lines=None,
        sources=sources,
        basis=basis,
        created_by_uuid=getattr(actor, "identity_uuid", None),
        created_by_name=getattr(actor, "display_name", None),
        what_changed=what_changed,
        is_demo=is_demo,
    )
    db.add(pack)
    db.flush()
    db.add(DraftStatusHistory(pack_id=pack.id, from_status=None, to_status="not_reviewed", system=True))
    if prev is not None and not prev.superseded:
        prev.superseded, prev.superseded_by = True, pack.id
        if prev.review_status not in ("filed_user_confirmed",):
            _history(db, prev, "superseded", actor=None, role=None, system=True, reason_text=what_changed)
        record_event(db, event_type="DRAFT_SUPERSEDED", category="agent", company_id=company_id, subject_type="draft_pack", subject_id=prev.id, details={"superseded_by": pack.id})
    bk.mark_draft_ready(db, company_id, tax_type, period_id)
    record_event(db, event_type="DRAFT_CREATED", category="agent", actor_key=actor_key, company_id=company_id, subject_type="draft_pack", subject_id=pack.id, details={"version": pack.version, "tax_type": tax_type, "period_id": period_id, "data_version": pack.data_version, "rule_version": pack.rule_version})
    record_event(db, event_type="DRAFT_READY", category="agent", company_id=company_id, subject_type="draft_pack", subject_id=pack.id, details={"k10": True, "k17": True, "version": pack.version})
    db.flush()
    return pack


def check_out_of_date(db: Session, pack: DraftPack) -> bool:
    """Source data or calculation changed after this version: system sets 'stale' and the pack is read-only."""
    if pack.superseded or pack.locked:
        return False
    calc = db.get(tax.CalculationResult, pack.calculation_id) if pack.calculation_id else None
    stale = False
    if calc is not None:
        tax.check_stale(db, calc)
        stale = calc.state == "stale" or data_version_for(calc) != pack.data_version
        newer = tax.latest(db, pack.company_id, pack.tax_type, pack.period_id)
        if newer is not None and newer.id != calc.id:
            stale = True
    if stale and pack.review_status != "stale":
        _history(db, pack, "stale", actor=None, role=None, system=True, reason_text="source data changed")
        pack.what_changed = pack.what_changed or "source data changed after this version"
        record_event(db, event_type="DRAFT_OUT_OF_DATE", category="agent", company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id)
        db.flush()
    return stale


# --- status transitions (role-bound) -----------------------------------------------------------

HUMAN_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "owner": {
        "not_reviewed": {"under_review"},
        "prepared": {"under_review"},
        "under_review": {"reviewed_with_changes", "accepted_by_reviewer"},
        "reviewed_with_changes": {"under_review", "accepted_by_reviewer"},
        "accepted_by_reviewer": {"under_review"},
        "accepted_by_owner_no_independent_review": {"under_review"},
        "reviewed_by_owner_after_hold": {"under_review", "accepted_by_reviewer"},
    },
    "delegate": {
        "not_reviewed": {"prepared", "under_review"},
        "prepared": {"under_review"},
        "under_review": {"reviewed_with_changes", "accepted_by_reviewer"},
        "reviewed_with_changes": {"under_review", "accepted_by_reviewer"},
        "accepted_by_reviewer": {"under_review"},
        "reviewed_by_owner_after_hold": {"under_review"},
    },
}
ROLE_FOR_STATUS = {"approved_for_submission": "Owner", "filed_user_confirmed": "Owner", "reviewed_by_specialist": "Tax specialist", "signed": "Licensed auditor", "superseded": "System", "stale": "System", "not_reviewed": "System"}


def transition(db: Session, pack: DraftPack, to_status: str, actor: Any, *, reason_code: str | None = None, reason_text: str | None = None, changed_fields: list[str] | None = None) -> DraftPack:
    if to_status not in DRAFT_STATUSES:
        raise ValidationFailed("unknown status", reason_code="VALIDATION_FAILED")
    if pack.superseded or pack.review_status in ("superseded",):
        raise Conflict("Approval is only possible on the current version.", reason_code="SUPERSEDED")
    if pack.locked:
        raise Conflict("this draft is locked (Filed, user-confirmed)", reason_code="LOCKED")
    if pack.on_hold:
        raise Conflict("this draft is on hold until the owner decides", reason_code="ON_HOLD")
    role = bk.role_for(actor, pack.company_id)
    staff = set(getattr(actor, "staff_roles", []) or [])
    if to_status in SYSTEM_ONLY_STATUSES:
        raise Forbidden("You cannot set this status. System can. Ask them or ask a human.", reason_code="SYSTEM_ONLY_STATUS", details={"role": "System"})
    if to_status in ("reviewed_by_specialist", "signed"):
        if not get_config(db, "drafts.specialist_status.enabled", False):
            raise SwitchedOff("specialist and auditor statuses are switched off until the service models are agreed (Increment C)", reason_code="FEATURE_SWITCHED_OFF")
        if to_status == "signed":
            raise Forbidden("'signed' applies to audit work only, never to a tax draft", reason_code="NOT_AUDIT_WORK")
        if "tax_specialist" not in staff:
            raise Forbidden("You cannot set this status. Tax specialist can. Ask them or ask a human.", reason_code="ROLE_CANNOT_SET_STATUS", details={"role": "Tax specialist"})
        _history(db, pack, to_status, actor=actor, role="tax_specialist", system=False, reason_code=reason_code, reason_text=reason_text)
        db.flush()
        return pack
    if to_status in ("approved_for_submission", "filed_user_confirmed"):
        raise Forbidden("You cannot set this status. Owner can. Ask them or ask a human.", reason_code="USE_APPROVALS", details={"role": "Owner", "hint": "approval acts go through the approvals module"})
    allowed = HUMAN_TRANSITIONS.get(role, {}).get(pack.review_status, set())
    if to_status not in allowed:
        who = ROLE_FOR_STATUS.get(to_status, "Owner")
        raise Forbidden(f"You cannot set this status. {who} can. Ask them or ask a human.", reason_code="ROLE_CANNOT_SET_STATUS", details={"role": who, "from": pack.review_status, "to": to_status})
    if pack.review_status in ("accepted_by_reviewer", "accepted_by_owner_no_independent_review") and to_status == "under_review":
        if not reason_code:
            raise ValidationFailed("Choose a reason to continue.", reason_code="REASON_REQUIRED")
        reason_code = reason_code or "reopen"
    if to_status == "accepted_by_reviewer":
        if pack.human_edited and pack.edited_by_uuid == actor.identity_uuid:
            raise Forbidden("The person who made a human edit cannot accept the same version.", reason_code="SELF_ACCEPT_REFUSED")
        no_source = [ln for ln in pack.lines if ln.get("no_source")]
        if no_source and not reason_code:
            raise ValidationFailed(f"Contains {len(no_source)} figures with no source. Record a reason to accept.", reason_code="REASON_REQUIRED", details={"no_source_count": len(no_source)})
        if role == "owner" and not _other_human_reviewed(db, pack, actor):
            to_status = "accepted_by_owner_no_independent_review"
    _history(db, pack, to_status, actor=actor, role=role, system=False, reason_code=reason_code, reason_text=reason_text, changed_fields=changed_fields)
    db.flush()
    return pack


def _other_human_reviewed(db: Session, pack: DraftPack, actor: Any) -> bool:
    rows = db.scalars(select(DraftStatusHistory).where(DraftStatusHistory.pack_id == pack.id, DraftStatusHistory.system.is_(False)))
    return any(r.actor_uuid and r.actor_uuid != actor.identity_uuid for r in rows)


def set_approval_status(db: Session, pack_id: str, status: str, *, actor: Any, expected_hash: str, filing_reference: str | None = None) -> DraftPack:
    """E6-S1 hook: records 'approved_for_submission' or 'filed_user_confirmed' bound to one version by hash."""
    pack = get_pack(db, pack_id)
    if status not in ("approved_for_submission", "filed_user_confirmed"):
        raise ValidationFailed("only approval statuses are set here")
    if pack.superseded or pack.review_status in ("superseded", "stale"):
        raise Conflict("Approval is only possible on the current version.", reason_code="SUPERSEDED")
    if pack.on_hold:
        raise Conflict("held drafts cannot be approved", reason_code="ON_HOLD")
    if expected_hash != pack_hash(pack):
        raise Conflict("the draft changed since it was shown; review the current version", reason_code="VERSION_CHANGED")
    _history(db, pack, status, actor=actor, role=bk.role_for(actor, pack.company_id), system=False)
    if status == "filed_user_confirmed":
        pack.locked, pack.filing_reference = True, filing_reference
    db.flush()
    return pack


def edit_figure(db: Session, pack: DraftPack, actor: Any, *, key: str, value_fils: int, reason_code: str, reason_text: str | None = None) -> DraftPack:
    """Human edit: keeps the AI version, marks human-edited, needs a reason from the rubric (six options)."""
    if pack.superseded or pack.locked or pack.on_hold:
        raise Conflict("this version cannot be edited", reason_code="READ_ONLY")
    rubric = get_config(db, "drafts.reason_rubric", REASON_RUBRIC_DEFAULT) or REASON_RUBRIC_DEFAULT
    if reason_code not in rubric:
        raise ValidationFailed("Choose a reason to continue.", reason_code="REASON_REQUIRED", details={"rubric": rubric})
    role = bk.role_for(actor, pack.company_id)
    if role not in ("owner", "delegate"):
        raise Forbidden("only the owner or a delegate may edit a draft", reason_code="NO_PERMISSION")
    if pack.ai_lines is None:
        pack.ai_lines = json.loads(json.dumps(pack.lines))
    lines = json.loads(json.dumps(pack.lines))
    target = next((ln for ln in lines if ln["key"] == key), None)
    if target is None:
        raise NotFound("figure not found", reason_code="NOT_FOUND")
    target["value_fils"] = value_fils
    target["line_class"] = "person_entered"
    target["source_refs"] = [{"source": "manual entry", "person": actor.display_name}]
    target["no_source"] = False
    target["human_edited"] = True
    pack.lines = lines
    pack.human_edited, pack.edited_by_uuid = True, actor.identity_uuid
    pack.last_human_change_by, pack.last_human_change_role, pack.last_human_change_at = actor.display_name, role, utcnow()
    changed = ["monetary_amount"]
    db.add(DraftStatusHistory(pack_id=pack.id, from_status=pack.review_status, to_status=pack.review_status, actor_uuid=actor.identity_uuid, actor_name=actor.display_name, actor_role=role, reason_code=reason_code, reason_text=reason_text, changed_fields=changed, material=bk.is_material(changed)))
    bk.record_review(db, pack.company_id, output_type="draft_pack", output_id=pack.id, outcome="corrected", changed_fields=changed, reviewer_uuid=actor.identity_uuid, reviewer_role=role)
    record_event(db, event_type="DRAFT_HUMAN_EDIT", category="sign_off", actor_key=actor.actor_key, actor_role=role, company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id, details={"key": key, "reason_code": reason_code, "material": True})
    db.flush()
    return pack


# --- quarantine (held drafts of a removed delegate) ----------------------------------------------


def hold_packs_for(db: Session, identity_uuid: str, company_id: str, *, display_name: str | None = None) -> int:
    n = 0
    for p in db.scalars(select(DraftPack).where(DraftPack.company_id == company_id, DraftPack.superseded.is_(False), DraftPack.locked.is_(False))):
        if identity_uuid in (p.created_by_uuid, p.edited_by_uuid):
            p.on_hold, p.held_delegate_uuid, p.held_delegate_name = True, identity_uuid, display_name or p.last_human_change_by or p.created_by_name
            p.held_changes = [ln["key"] for ln in p.lines if ln.get("human_edited")] or ["prepared this version"]
            n += 1
            record_event(db, event_type="DRAFT_HELD", category="agent", company_id=company_id, subject_type="draft_pack", subject_id=p.id, details={"version": p.version})
    db.flush()
    return n


def decide_hold(db: Session, pack: DraftPack, actor: Any, *, decision: str, reason_code: str, reason_text: str | None = None) -> dict:
    """Owner only, one draft at a time, mandatory reason. Keep | Discard (return to last unchanged) | Ask a human."""
    if bk.role_for(actor, pack.company_id) != "owner":
        raise Forbidden("You do not have access to this page.", reason_code="NO_PERMISSION")
    if not pack.on_hold:
        raise Conflict("this draft is not on hold", reason_code="NOT_ON_HOLD")
    if not reason_code:
        raise ValidationFailed("Choose a reason to continue.", reason_code="REASON_REQUIRED")
    if decision not in ("keep_changes", "discard_changes", "ask_a_human"):
        raise ValidationFailed("unknown decision")
    result: dict = {"decision": decision}
    if decision == "ask_a_human":
        record_event(db, event_type="DRAFT_HOLD_ASK_HUMAN", category="escalation", actor_key=actor.actor_key, actor_role="owner", company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id, details={"reason_code": reason_code})
        result["status"] = "asked_a_human"
        db.flush()
        return result
    pack.on_hold = False
    new = DraftPack(company_id=pack.company_id, tax_type=pack.tax_type, period_id=pack.period_id, version=pack.version + 1, data_version=pack.data_version, rule_version=pack.rule_version, calculation_id=pack.calculation_id, assumptions=pack.assumptions, sources=pack.sources, basis=pack.basis, created_by_uuid=actor.identity_uuid, created_by_name=actor.display_name, what_changed=f"owner decided held version {pack.version}: {decision}")
    if decision == "keep_changes":
        new.lines, new.ai_lines, new.human_edited, new.edited_by_uuid = pack.lines, pack.ai_lines, pack.human_edited, pack.edited_by_uuid
        new.review_status = "reviewed_by_owner_after_hold"
    else:
        new.lines, new.human_edited, new.edited_by_uuid = (pack.ai_lines or pack.lines), False, None
        new.review_status = "not_reviewed"
    db.add(new)
    db.flush()
    db.add(DraftStatusHistory(pack_id=new.id, from_status=None, to_status=new.review_status, actor_uuid=actor.identity_uuid, actor_name=actor.display_name, actor_role="owner", reason_code=reason_code, reason_text=reason_text))
    pack.superseded, pack.superseded_by = True, new.id
    _history(db, pack, "superseded", actor=None, role=None, system=True, reason_text=f"owner decision: {decision}")
    record_event(db, event_type="DRAFT_HOLD_DECIDED", category="sign_off", actor_key=actor.actor_key, actor_role="owner", company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id, details={"decision": decision, "reason_code": reason_code, "new_version": new.version, "changes": len(pack.held_changes or [])})
    still = db.scalar(select(DraftPack).where(DraftPack.company_id == pack.company_id, DraftPack.on_hold.is_(True)).limit(1))
    remaining = len(list(db.scalars(select(DraftPack).where(DraftPack.company_id == pack.company_id, DraftPack.on_hold.is_(True))))) if still else 0
    result |= {"new_pack_id": new.id, "new_version": new.version, "still_on_hold": remaining, "announcement": f"Draft discarded. {remaining} drafts still on hold." if decision == "discard_changes" else None}
    db.flush()
    return result


# --- read / export ------------------------------------------------------------------------------


def pack_dict(db: Session, pack: DraftPack, *, role: str = "owner", lang: str = "en") -> dict:
    history = list(db.scalars(select(DraftStatusHistory).where(DraftStatusHistory.pack_id == pack.id).order_by(DraftStatusHistory.at)))
    no_source = [ln for ln in pack.lines if ln.get("no_source")]
    versions = list(db.scalars(select(DraftPack).where(DraftPack.company_id == pack.company_id, DraftPack.tax_type == pack.tax_type, DraftPack.period_id == pack.period_id).order_by(DraftPack.version)))
    current = versions[-1] if versions else pack
    return {
        "id": pack.id,
        "company_id": pack.company_id,
        "tax_type": pack.tax_type,
        "period_id": pack.period_id,
        "version": pack.version,
        "is_current": current.id == pack.id,
        "current_version": current.version,
        "current_pack_id": current.id,
        "ai_label": {"en": pack.ai_label_en, "ar": pack.ai_label_ar},
        "watermark": WATERMARK,
        "emaratax_sentence": EMARATAX_SENTENCE,
        "product_name": PRODUCT_NAME,
        "review_status": pack.review_status,
        "review_status_label": STATUS_LABELS.get(pack.review_status, {"en": pack.review_status, "ar": pack.review_status}),
        "not_reviewed_by_human": pack.review_status in ("not_reviewed", "prepared", "stale"),
        "data_version": pack.data_version,
        "rule_version": pack.rule_version,
        "calculation_id": pack.calculation_id,
        "assumptions": pack.assumptions,
        "lines": pack.lines,
        "ai_lines": pack.ai_lines,
        "sources": pack.sources if role in ("owner", "delegate", "licensed_auditor", "specialist") else [],
        "basis": pack.basis,
        "human_edited": pack.human_edited,
        "last_human_change": {"by": pack.last_human_change_by, "role": pack.last_human_change_role, "at": pack.last_human_change_at.isoformat() if pack.last_human_change_at else None},
        "on_hold": pack.on_hold,
        "held": {"delegate": pack.held_delegate_name, "changes": pack.held_changes} if pack.on_hold else None,
        "superseded": pack.superseded,
        "superseded_by": pack.superseded_by,
        "what_changed": pack.what_changed,
        "locked": pack.locked,
        "filing_reference": pack.filing_reference,
        "no_source_count": len(no_source),
        "pack_hash": pack_hash(pack),
        "created_at": pack.created_at.isoformat(),
        "created_by": pack.created_by_name,
        "is_demo": pack.is_demo,
        "can_approve": (not pack.superseded) and (not pack.on_hold) and (not pack.locked) and pack.review_status not in ("stale", "superseded"),
        "approve_disabled_reason": None if (not pack.superseded and not pack.on_hold and not pack.locked and pack.review_status not in ("stale", "superseded")) else ("Approval is only possible on the current version." if (pack.superseded or pack.review_status in ("stale", "superseded")) else "held drafts cannot be approved or exported" if pack.on_hold else "locked"),
        "allowed_transitions": sorted(HUMAN_TRANSITIONS.get(role, {}).get(pack.review_status, set())) if not (pack.superseded or pack.on_hold or pack.locked) else [],
        "history": [{"from": h.from_status, "to": h.to_status, "by": h.actor_name, "role": h.actor_role, "system": h.system, "reason_code": h.reason_code, "changed_fields": h.changed_fields, "material": h.material, "at": h.at.isoformat()} for h in history],
        "versions": [{"id": v.id, "version": v.version, "review_status": v.review_status, "superseded": v.superseded} for v in versions],
        "retention": {"note": "Your company remains responsible for its statutory records and can export them.", "classes": get_config(db, "drafts.retention_classes", RETENTION_CLASSES_DEFAULT)},
    }


def export_pack(db: Session, pack: DraftPack, actor: Any, *, lang: str) -> dict:
    """Export: labels follow the language choice; source values never change. Logged (Q435 formats open)."""
    if pack.on_hold:
        raise Conflict("held drafts cannot be approved or exported", reason_code="ON_HOLD")
    if lang not in ("en", "ar"):
        raise ValidationFailed("language must be en or ar")
    exp = DraftExport(pack_id=pack.id, language=lang, format="json", exported_by_uuid=actor.identity_uuid)
    db.add(exp)
    record_event(db, event_type="DRAFT_EXPORTED", category="document", actor_key=actor.actor_key, actor_role=bk.role_for(actor, pack.company_id), company_id=pack.company_id, subject_type="draft_pack", subject_id=pack.id, details={"language": lang, "format": "json", "export_id": exp.id, "retention_class": 3})
    db.flush()
    doc = {
        "export_id": exp.id,
        "language": lang,
        "title": f"{PRODUCT_NAME[lang]}: {('VAT' if pack.tax_type == 'vat' else 'Corporate tax')} draft {pack.period_id} v{pack.version}",
        "label": pack.ai_label_ar if lang == "ar" else pack.ai_label_en,
        "watermark": WATERMARK[lang],
        "draft_statement": EMARATAX_SENTENCE[lang],
        "status": STATUS_LABELS.get(pack.review_status, {}).get(lang, pack.review_status),
        "data_version": pack.data_version,
        "rule_version": pack.rule_version,
        "lines": [{"key": ln["key"], "term": ln["term"][lang], "gloss": ln["gloss"][lang], "value_fils": ln["value_fils"], "text": ln.get("text"), "line_class": ln["line_class"], "no_source": ln.get("no_source"), "source_refs": ln.get("source_refs")} for ln in pack.lines],
        "sources": pack.sources,
        "basis": pack.basis,
        "pack_hash": pack_hash(pack),
        "pdf": {"available": False, "note": "tagged PDF with embedded Arabic/Latin fonts is a later export format (Q435 open); this JSON export carries the same label, status, data version and draft statement"},
    }
    return doc

