"""E7-S3 draft audit working file ('audit work draft' / 'مسودة أعمال تدقيق').

Completeness rule set ac-v1 (checks a-f): incomplete / complete / complete_with_exceptions. 'Complete' means ready
for licensed-auditor review, never sufficient to sign. Status machine: draft -> under_review -> signed | rejected;
rejected -> draft. 'Issued' is reachable only through the documents module from a signed version; any attempt to
release an unsigned draft is refused and logged as release_blocked. Every unsigned export carries the fixed
bilingual watermark, the page-1 notice and the gap list.
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.auditagent.models import (
    FILE_TRANSITIONS,
    AuditWorkingFile,
    DataGap,
    Engagement,
    ExceptionFlag,
    FileStatusHistory,
)
from app.modules.auditagent.strings import WATERMARK, both, s
from app.modules.config.service import get_config

GAP_TEXT = {
    "a": {"item_en": "Ledger records for every month of {period}", "item_ar": "سجلات الدفاتر لكل شهر من {period}", "why_en": "The draft must cover the full tax period.", "why_ar": "يجب أن تغطي المسودة الفترة الضريبية كاملة.", "action": "add_statements"},
    "b": {"item_en": "Trial balance for {period}", "item_ar": "ميزان المراجعة لـ {period}", "why_en": "An unbalanced or missing trial balance keeps the draft incomplete.", "why_ar": "يبقى ميزان المراجعة غير المتوازن أو المفقود المسودة غير مكتملة.", "action": "ask_my_accountant"},
    "f": {"item_en": "Owner confirmation of revenue, tax group and free-zone status", "item_ar": "تأكيد المالك للإيرادات ووضع المجموعة الضريبية والمنطقة الحرة", "why_en": "Audit-required inputs must be confirmed by the owner.", "why_ar": "يجب أن يؤكد المالك مدخلات مؤشر التدقيق.", "action": "ask_my_accountant"},
}
EXTERNAL_EVIDENCE = ["bank confirmations", "inventory count", "legal letters", "management representations"]
REGISTERS = ["fixed assets register", "receivables listing", "payables listing", "VAT returns filed in period", "corporate tax position"]


def _int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_config(db, key, default))
    except (TypeError, ValueError):
        return default


def current_file(db: Session, company_id: str) -> AuditWorkingFile | None:
    return db.scalar(select(AuditWorkingFile).where(AuditWorkingFile.company_id == company_id, AuditWorkingFile.is_current.is_(True)).order_by(AuditWorkingFile.created_at.desc()).limit(1))


def get_file(db: Session, company_id: str, file_id: str) -> AuditWorkingFile:
    f = db.get(AuditWorkingFile, file_id)
    if f is None or f.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    return f


def active_engagement(db: Session, f: AuditWorkingFile | None, company_id: str | None = None) -> Engagement | None:
    cid = f.company_id if f else company_id
    stmt = select(Engagement).where(Engagement.company_id == cid, Engagement.status != "not_assigned")
    return db.scalar(stmt.order_by(Engagement.assigned_at.desc()).limit(1))


def content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _history(db: Session, f: AuditWorkingFile, frm: str | None, to: str, who: str, role: str) -> None:
    db.add(FileStatusHistory(file_id=f.id, who=who, role=role, from_status=frm, to_status=to))


def transition(db: Session, f: AuditWorkingFile, to: str, *, who: str, role: str, actor_key: str | None = None, via_signing: bool = False) -> AuditWorkingFile:
    """Only draft->under_review, under_review->signed (licensed sign-off only), under_review->rejected, rejected->draft."""
    if to not in ("draft", "under_review", "signed", "rejected") or (f.status, to) not in FILE_TRANSITIONS or (to == "signed" and not via_signing):
        f.release_blocked = to in ("issued", "signed", "audit_report", "audit_certificate")
        record_event(db, event_type="RELEASE_BLOCKED" if f.release_blocked else "STATUS_CHANGE_REFUSED", category="sign_off", outcome="refused", reason_code="TRANSITION_NOT_ALLOWED", actor_key=actor_key, actor_role=role, company_id=f.company_id, subject_type="audit_working_file", subject_id=f.id, details={"from": f.status, "to": to})
        raise Conflict("this status change is not allowed for an unsigned draft", reason_code="TRANSITION_NOT_ALLOWED", details={"from": f.status, "to": to})
    _history(db, f, f.status, to, who, role)
    record_event(db, event_type="STATUS_CHANGED", category="sign_off", actor_key=actor_key, actor_role=role, company_id=f.company_id, subject_type="audit_working_file", subject_id=f.id, details={"from": f.status, "to": to, "version_no": f.version_no})
    f.status = to
    db.flush()
    return f


def attempt_release(db: Session, f: AuditWorkingFile, *, who: str, role: str, actor_key: str | None = None, wording: str | None = None) -> dict:
    """Any attempt to mark an unsigned output 'issued' or call it audit report/certificate is refused and logged."""
    f.release_blocked = True
    record_event(db, event_type="RELEASE_BLOCKED", category="sign_off", outcome="refused", reason_code="UNSIGNED_DRAFT", actor_key=actor_key, actor_role=role, company_id=f.company_id, subject_type="audit_working_file", subject_id=f.id, details={"status": f.status, "wording_blocked": bool(wording)})
    db.flush()
    raise Forbidden(s("blocked_release", "en", reason="Only a licensed auditor's signature can make it final"), reason_code="RELEASE_BLOCKED", details={"message": both("blocked_release", reason="")})


# --- preparation (ac-v1) ---------------------------------------------------------------------------------


def _period_label(ps: date, pe: date) -> str:
    return f"{ps.isoformat()} to {pe.isoformat()}"


def evaluate_checks(db: Session, company_id: str, ps: date, pe: date) -> tuple[dict, list[str]]:
    """Machine-checkable ac-v1 checks; returns (checks, blocking failures)."""
    from app.modules.auditagent.review import source_gate

    checks: dict[str, Any] = {}
    blocking: list[str] = []
    months_needed = {(ps.year + (ps.month - 1 + i) // 12, (ps.month - 1 + i) % 12 + 1) for i in range(((pe.year - ps.year) * 12 + pe.month - ps.month) + 1)}
    months_have: set = set()
    try:
        from app.modules.bookkeeping.service import confirmed_transactions

        months_have = {(t.txn_date.year, t.txn_date.month) for _, t in confirmed_transactions(db, company_id, ps, pe)}
    except ImportError:  # pragma: no cover
        pass
    a_ok = months_needed <= months_have
    checks["a"] = {"name": "period coverage", "status": "pass" if a_ok else "fail", "blocking": True, "months_covered": len(months_have & months_needed), "months_needed": len(months_needed)}
    if not a_ok:
        blocking.append("a")
    checks["b"] = {"name": "trial balance balanced", "status": "not_provided", "blocking": True}
    blocking.append("b")  # no trial balance source in Phase 1 data: always incomplete until supplied
    bank = source_gate(db, company_id, "bank")
    checks["c"] = {"name": "bank data", "status": "pass" if bank.get("allowed") else "bank_evidence_not_provided", "blocking": False, "label": both("bank_evidence_not_provided") if not bank.get("allowed") else None}
    open_items = len(list(db.scalars(select(ExceptionFlag.id).where(ExceptionFlag.company_id == company_id, ExceptionFlag.rule_id.in_(("AX04", "AX05")), ExceptionFlag.status == "New"))))
    thr = get_config(db, "auditagent.reconciliation.unreconciled_threshold", None)
    checks["d"] = {"name": "bank reconciliation", "status": "exceptions" if (thr is not None and open_items > int(thr)) else "pass", "blocking": False, "unreconciled_items": open_items, "threshold": thr}
    checks["e"] = {"name": "supporting registers", "status": "not_provided", "blocking": False, "registers": [{"item": r, "status": "not provided"} for r in REGISTERS], "to_be_obtained_by_auditor": EXTERNAL_EVIDENCE}
    from app.modules.auditagent.indicator import resolve_inputs

    inp = resolve_inputs(db, company_id)
    f_ok = inp.get("tax_group") in ("yes", "no") and any(x.get("owner_confirmed") for x in inp.get("figures", []))
    checks["f"] = {"name": "audit-required inputs owner-confirmed", "status": "pass" if f_ok else "fail", "blocking": True}
    if not f_ok:
        blocking.append("f")
    return checks, blocking


def prepare_working_file(db: Session, company_id: str, *, period: tuple[date, date] | None = None, actor_key: str | None = None, today: date | None = None, is_demo: bool = False, completeness_override: str | None = None) -> dict:
    """Prepare (or revise) the draft. Refused run when no consented source exists: no draft, no partial figures."""
    from app.modules.auditagent.review import default_period, source_gate

    today = today or dubai_today()
    if period is None:
        ps, pe, _ = default_period(db, company_id, today)
    else:
        ps, pe = period
    ledger = source_gate(db, company_id, "ledger", actor_key=actor_key)
    if not ledger.get("allowed") and completeness_override is None:
        cause = "consent_expired" if ledger.get("state") in ("withdrawn", "expired") else "no_statements"
        record_event(db, event_type="RUN_REFUSED", category="agent", outcome="refused", reason_code=cause.upper(), actor_key=actor_key, company_id=company_id, details={"check_version": "ac-v1", "no_data_read": True})
        return {"refused": True, "cause": cause, "message": both("refused_run", cause="consent for bank data has expired" if cause == "consent_expired" else "no statements have been added", step="Renew consent" if cause == "consent_expired" else "Add statements"), "no_data_read": both("no_data_read")}
    if completeness_override:  # labelled demo fixture state (Demo data)
        checks = {k: {"name": n, "status": "pass", "blocking": k in ("a", "b", "f")} for k, n in (("a", "period coverage"), ("b", "trial balance balanced"), ("c", "bank data"), ("d", "bank reconciliation"), ("e", "supporting registers"), ("f", "audit-required inputs owner-confirmed"))}
        checks["c"]["status"] = "bank_evidence_not_provided"
        checks["e"]["to_be_obtained_by_auditor"] = EXTERNAL_EVIDENCE
        if completeness_override == "complete_with_exceptions":
            checks["d"]["status"] = "exceptions"
        blocking = [] if completeness_override != "incomplete" else ["b"]
    else:
        checks, blocking = evaluate_checks(db, company_id, ps, pe)
    flags = list(db.scalars(select(ExceptionFlag).where(ExceptionFlag.company_id == company_id)))
    open_exc = [fl for fl in flags if fl.status in ("New", "Escalated", "Confirmed")]
    if completeness_override:
        state = completeness_override
    elif blocking:
        state = "incomplete"
    elif open_exc or any(c.get("status") == "exceptions" for c in checks.values()):
        state = "complete_with_exceptions"
    else:
        state = "complete"
    content = _ai_content(db, company_id, ps, pe, blocking)
    h = content_hash(content)
    f = db.scalar(select(AuditWorkingFile).where(AuditWorkingFile.company_id == company_id, AuditWorkingFile.period_start == ps, AuditWorkingFile.period_end == pe, AuditWorkingFile.is_current.is_(True)))
    created = False
    if f is None:
        f = AuditWorkingFile(company_id=company_id, period_start=ps, period_end=pe, is_demo=is_demo)
        db.add(f)
        created = True
    elif f.content_hash and f.content_hash != h:
        f = edit_content(db, f, content=content, who="AI agent", role="agent", actor_key=actor_key)
    prev_state = f.completeness_state if not created else None
    f.checks, f.ai_prepared_content, f.content_hash = checks, content, h
    f.source_record_links = content.get("source_record_links", [])
    f.calculation_basis = content.get("basis", {})
    f.exception_ids = [fl.id for fl in flags]
    f.completeness_state = state
    if state in ("complete", "complete_with_exceptions") and f.first_complete_draft_ready_at is None:
        f.first_complete_draft_ready_at = utcnow()  # immutable K18 clock stop
    if prev_state in ("complete", "complete_with_exceptions") and state == "incomplete":
        f.reopen_count += 1
    db.flush()
    for fl in flags:
        fl.audit_file_id = fl.audit_file_id or f.id
    _sync_gaps(db, f, blocking, ps, pe)
    if created:
        _history(db, f, None, "draft", "AI agent", "agent")
        record_event(db, event_type="DRAFT_CREATED", category="agent", actor_key=actor_key, company_id=company_id, subject_type="audit_working_file", subject_id=f.id, details={"check_version": "ac-v1", "completeness": state})
    if state == "incomplete":
        record_event(db, event_type="DRAFT_MARKED_INCOMPLETE", category="agent", company_id=company_id, subject_type="audit_working_file", subject_id=f.id, details={"failed_checks": blocking})
    db.flush()
    return {"refused": False, "file_id": f.id, "completeness_state": state}


def _ai_content(db: Session, company_id: str, ps: date, pe: date, blocking: list[str]) -> dict:
    rows = []
    try:
        from app.modules.bookkeeping.service import confirmed_transactions

        rows = confirmed_transactions(db, company_id, ps, pe)
    except ImportError:  # pragma: no cover
        pass
    income = [(c, t) for c, t in rows if t.direction == "in"]
    spend = [(c, t) for c, t in rows if t.direction == "out"]
    gap_no = {code: i + 1 for i, code in enumerate(blocking)}
    figures = [
        {"key": "receipts_total", "label": {"en": "Receipts recorded in the period", "ar": "المقبوضات المسجلة في الفترة"}, "value_fils": sum(t.aed_amount_fils for _, t in income) if "a" not in gap_no else None, "gap": gap_no.get("a"), "source_refs": [t.id for _, t in income][:50]},
        {"key": "payments_total", "label": {"en": "Payments recorded in the period", "ar": "المدفوعات المسجلة في الفترة"}, "value_fils": sum(t.aed_amount_fils for _, t in spend) if "a" not in gap_no else None, "gap": gap_no.get("a"), "source_refs": [t.id for _, t in spend][:50]},
        {"key": "trial_balance", "label": {"en": "Trial balance", "ar": "ميزان المراجعة"}, "value_fils": None, "gap": gap_no.get("b"), "source_refs": []},
    ]
    return {"figures": figures, "source_record_links": sorted({t.id for _, t in rows})[:200], "basis": {"rule_set": "ac-v1", "receipts": "sum of person-confirmed entries with direction 'in'", "payments": "sum of person-confirmed entries with direction 'out'", "missing": "missing figures show Gap n, never zero or a guess"}, "record_count": len(rows)}


def _sync_gaps(db: Session, f: AuditWorkingFile, blocking: list[str], ps: date, pe: date) -> None:
    existing = {g.check: g for g in db.scalars(select(DataGap).where(DataGap.file_id == f.id))}
    n = max((g.gap_number for g in existing.values()), default=0)
    for code in blocking:
        if code in existing or code not in GAP_TEXT:
            if code in existing and existing[code].status == "received":
                existing[code].status = "open"
            continue
        n += 1
        t = GAP_TEXT[code]
        period = _period_label(ps, pe)
        db.add(DataGap(file_id=f.id, company_id=f.company_id, gap_number=n, check=code, item_en=t["item_en"].format(period=period), item_ar=t["item_ar"].format(period=period), why_en=t["why_en"], why_ar=t["why_ar"], action=t["action"], history=[{"what": "created", "by": "AI agent", "at": utcnow().isoformat()}]))
    for code, g in existing.items():
        if code not in blocking and g.status in ("open", "requested", "overdue"):
            g.status = "received"
    db.flush()


def edit_content(db: Session, f: AuditWorkingFile, *, content: dict, who: str, role: str, actor_key: str | None = None) -> AuditWorkingFile:
    """Content edit: after under_review -> back to draft, earlier review invalid; after a recorded review or a signature
    -> new unsigned version (signature void), auditor notified."""
    from app.modules.auditagent.models import AuditorReviewRecord, SignedOutsideRecord

    eng = active_engagement(db, f)
    reviewed = eng is not None and db.scalar(select(AuditorReviewRecord.id).where(AuditorReviewRecord.engagement_id == eng.id, AuditorReviewRecord.file_id == f.id, AuditorReviewRecord.void.is_(False)).limit(1)) is not None
    signed = f.status == "signed" or (eng is not None and db.scalar(select(SignedOutsideRecord.id).where(SignedOutsideRecord.engagement_id == eng.id, SignedOutsideRecord.is_current.is_(True)).limit(1)) is not None)
    now = utcnow()
    if reviewed or signed:
        f.is_current = False
        nf = AuditWorkingFile(company_id=f.company_id, period_start=f.period_start, period_end=f.period_end, version_no=f.version_no + 1, status="draft", completeness_state=f.completeness_state, first_draft_created_at=f.first_draft_created_at, first_complete_draft_ready_at=f.first_complete_draft_ready_at, reopen_count=f.reopen_count, engagement_id=f.engagement_id, ai_prepared_content=content, content_hash=content_hash(content), signature_void=True, changed_on=now, changed_by=who, is_demo=f.is_demo, checks=f.checks)
        db.add(nf)
        db.flush()
        for rr in db.scalars(select(AuditorReviewRecord).where(AuditorReviewRecord.file_id == f.id)):
            rr.void = True
        for g in db.scalars(select(DataGap).where(DataGap.file_id == f.id)):
            db.add(DataGap(file_id=nf.id, company_id=g.company_id, gap_number=g.gap_number, check=g.check, item_en=g.item_en, item_ar=g.item_ar, why_en=g.why_en, why_ar=g.why_ar, who_can_fix=g.who_can_fix, status=g.status, action=g.action, history=list(g.history or [])))
        if eng is not None:
            eng.working_file_id, eng.status, eng.last_activity_at = nf.id, "awaiting_review", now
        _history(db, nf, None, "draft", who, role)
        record_event(db, event_type="SIGNATURE_VOID", category="sign_off", actor_key=actor_key, actor_role=role, company_id=f.company_id, subject_type="audit_working_file", subject_id=nf.id, details={"previous_version": f.version_no, "version_no": nf.version_no})
        record_event(db, event_type="VERSION_CREATED_ON_EDIT", category="sign_off", company_id=f.company_id, subject_type="audit_working_file", subject_id=nf.id, details={"notify": "auditor portal + email, 3 retries"})
        db.flush()
        return nf
    was_under_review = f.status == "under_review"
    if was_under_review:
        for h in db.scalars(select(FileStatusHistory).where(FileStatusHistory.file_id == f.id, FileStatusHistory.to_status == "under_review", FileStatusHistory.invalid.is_(False))):
            h.invalid, h.invalid_since, h.invalid_reason = True, now, "data_edited"
        _history(db, f, "under_review", "draft", who, role)
        f.status = "draft"
        record_event(db, event_type="EDIT_AFTER_REVIEW_RESET", category="sign_off", actor_key=actor_key, actor_role=role, company_id=f.company_id, subject_type="audit_working_file", subject_id=f.id, details={"review_invalidated": True})
    f.out_of_date, f.changed_on, f.changed_by = was_under_review or f.out_of_date, now, who
    f.ai_prepared_content, f.content_hash = content, content_hash(content)
    db.flush()
    return f


# --- data gaps and delegate data requests ---------------------------------------------------------------------


def get_gap(db: Session, company_id: str, gap_id: str) -> DataGap:
    g = db.get(DataGap, gap_id)
    if g is None or g.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    return g


def gap_action(db: Session, g: DataGap, *, action: str, actor_name: str, actor_role: str, actor_key: str | None, assignee_uuid: str | None = None, assignee_name: str | None = None, due_date: date | None = None, reason: str | None = None) -> DataGap:
    now = utcnow()
    if action == "request":
        g.status, g.assignee_uuid, g.assignee_name = "requested", assignee_uuid, assignee_name
        g.due_date = due_date or (dubai_today() + timedelta(days=_int(db, "auditagent.data_request.default_due_days", 7)))
    elif action == "provided":
        g.status, g.provided_at = "received", now  # owner notified; revised draft prepared
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=g.company_id, subject_type="data_gap", subject_id=g.id, details={"kind": "data_provided", "to": "owner"})
    elif action == "reopen":
        if not reason or len(reason.strip()) < 10:
            raise ValidationFailed("reopening needs a reason", reason_code="REASON_TOO_SHORT")
        g.status = "open"
    elif action == "reassign":
        g.assignee_uuid, g.assignee_name, g.reassigned_note = assignee_uuid, assignee_name, False
    elif action == "do_it_myself":
        g.assignee_uuid, g.assignee_name = None, actor_name
    else:
        raise ValidationFailed("unknown action", reason_code="ACTION_INVALID")
    g.history = list(g.history or []) + [{"what": action, "by": actor_name, "role": actor_role, "at": now.isoformat()}]
    record_event(db, event_type=f"DATA_REQUEST_{action.upper()}", category="agent", actor_key=actor_key, actor_role=actor_role, company_id=g.company_id, subject_type="data_gap", subject_id=g.id)
    db.flush()
    return g


def run_gap_reminders(db: Session, today: date | None = None) -> int:
    """Reminders on the due date and +3 days, then 'Overdue, no response'; nothing further automatic."""
    today = today or dubai_today()
    plus = _int(db, "auditagent.data_request.second_reminder_days", 3)
    n = 0
    for g in db.scalars(select(DataGap).where(DataGap.status.in_(("requested", "overdue")), DataGap.due_date.is_not(None))):
        sent = list(g.reminders_sent or [])
        for label, when in (("due", g.due_date), ("plus3", g.due_date + timedelta(days=plus))):
            if today >= when and label not in sent:
                sent.append(label)
                n += 1
                record_event(db, event_type="DATA_REQUEST_REMINDER_SENT", category="reminder", company_id=g.company_id, subject_type="data_gap", subject_id=g.id, details={"reminder": label})
        g.reminders_sent = sent
        if today > g.due_date + timedelta(days=plus) and g.status != "overdue":
            g.status = "overdue"
            record_event(db, event_type="DATA_REQUEST_OVERDUE", category="reminder", company_id=g.company_id, subject_type="data_gap", subject_id=g.id)
    db.flush()
    return n


# --- presentation and export ----------------------------------------------------------------------------------


def status_label(db: Session, f: AuditWorkingFile | None) -> dict:
    """Honest status: 'awaiting licensed auditor' appears only when a named licensed-auditor engagement exists."""
    if f is None:
        return both("status_not_started")
    eng = active_engagement(db, f)
    if f.status == "draft":
        return both("status_awaiting_auditor") if (eng is not None and eng.auditor_name) else both("status_no_auditor")
    if f.status == "under_review":
        return both("status_under_review") if eng is not None else both("status_under_review_short")
    if f.status == "rejected":
        return both("status_rejected")
    return both("status_signed_outside")


def gaps_for(db: Session, f: AuditWorkingFile) -> list[DataGap]:
    order = {"overdue": 0, "open": 1, "requested": 2, "received": 3}
    return sorted(db.scalars(select(DataGap).where(DataGap.file_id == f.id)), key=lambda g: (order.get(g.status, 9), g.gap_number))


def gap_dict(g: DataGap) -> dict:
    return {"id": g.id, "gap_number": g.gap_number, "check": g.check, "item": {"en": g.item_en, "ar": g.item_ar}, "why": {"en": g.why_en, "ar": g.why_ar}, "who_can_fix": g.who_can_fix, "status": g.status, "action": g.action, "assignee_name": g.assignee_name, "due_date": g.due_date.isoformat() if g.due_date else None, "history": g.history, "reminders_sent": g.reminders_sent, "held_for_owner_review": g.held_for_owner_review, "reassigned_note": g.reassigned_note}


def file_dict(db: Session, f: AuditWorkingFile, *, role: str = "owner") -> dict:
    from app.modules.auditagent.models import AuditorReviewRecord, ReturnRecord, SignedOutsideRecord

    eng = active_engagement(db, f)
    gaps = gaps_for(db, f)
    complete = sum(1 for g in gaps if g.status == "received")
    hist = [{"who": h.who, "role": h.role, "at": h.at.isoformat(), "from": h.from_status, "to": h.to_status, "invalid": h.invalid, "invalid_since": h.invalid_since.isoformat() if h.invalid_since else None} for h in db.scalars(select(FileStatusHistory).where(FileStatusHistory.file_id == f.id).order_by(FileStatusHistory.at))]
    ret = db.scalar(select(ReturnRecord).where(ReturnRecord.file_id == f.id).order_by(ReturnRecord.at.desc()).limit(1)) if eng else None
    review = db.scalar(select(AuditorReviewRecord).where(AuditorReviewRecord.file_id == f.id, AuditorReviewRecord.void.is_(False)).order_by(AuditorReviewRecord.recorded_at.desc()).limit(1))
    outside = db.scalar(select(SignedOutsideRecord).where(SignedOutsideRecord.engagement_id == eng.id, SignedOutsideRecord.is_current.is_(True)).limit(1)) if eng else None
    staff_view = role in ("licensed_auditor", "qeonix_audit_ops")
    return {
        "id": f.id, "company_id": f.company_id, "period_start": f.period_start.isoformat(), "period_end": f.period_end.isoformat(), "version_no": f.version_no,
        "deliverable_type": f.deliverable_type, "type_class": f.type_class, "signature_required": f.signature_required, "provisional": f.provisional,
        "name": both("deliverable_name"), "title": both("file_title"), "status": f.status, "status_label": status_label(db, f), "header": {"en": s("header_label", "en", status=status_label(db, f)["en"]), "ar": s("header_label", "ar", status=status_label(db, f)["ar"])},
        "completeness_state": f.completeness_state, "check_version": f.check_version, "checks": f.checks, "sign_off_status": "not_ready" if f.completeness_state == "incomplete" else "ready_for_review",
        "complete_means": {"en": "Complete means ready for licensed-auditor review. It is never sufficient to sign.", "ar": "مكتملة تعني جاهزة لمراجعة مدقق مرخّص، ولا تكفي أبدًا للتوقيع."},
        "first_complete_draft_ready_at": f.first_complete_draft_ready_at.isoformat() if f.first_complete_draft_ready_at else None, "first_draft_created_at": f.first_draft_created_at.isoformat(), "reopen_count": f.reopen_count,
        "out_of_date": f.out_of_date, "changed_on": f.changed_on.isoformat() if f.changed_on else None, "changed_by": f.changed_by, "signature_void": f.signature_void, "release_blocked": f.release_blocked,
        "watermark": WATERMARK, "watermark_fixed": True, "page1_notice": both("page1_notice"), "fixed_draft_text": both("fixed_draft_text"),
        "ai_prepared_content": f.ai_prepared_content, "human_approved_content": f.human_approved_content, "reviewer_name": f.reviewer_name,
        "gaps": [gap_dict(g) for g in gaps], "gaps_summary": {"complete": complete, "total": len(gaps)}, "history": hist,
        "engagement": None if eng is None else {"id": eng.id, "status": eng.status, "auditor_assigned": True, "engagement_manager_role": "Licensed auditor firm contact" if not eng.engagement_manager_is_fallback else "DET pilot manager queue", "preparing_team_role": "Qeonix audit operations", "auditor_name": eng.auditor_name if staff_view else None},
        "return": None if ret is None else {"kind": ret.kind, "reason_code": ret.reason_code, "at": ret.at.isoformat(), "by_role": "Licensed auditor", "free_text": ret.free_text if (ret.release_free_text or staff_view) else None, "reason_language": ret.reason_language, "not_yet_translated": True},
        "review_recorded": None if review is None else {"text": both("review_recorded", name=review.reviewer_name, x=review.register_no or "", date=review.recorded_at.date().isoformat()), "label": review.label, "supplied_documents_only": review.supplied_documents_only, "supplied_documents_text": both("supplied_documents_only") if review.supplied_documents_only else None},
        "signed_outside": None if outside is None else {"text": both("signed_outside", name=outside.reporter_name, role=outside.reporter_role, date=outside.date_signed.isoformat()), "badge": {"en": "not verified by the platform", "ar": "لم تتحقق منه المنصة"}},
        "signing_available": bool(get_config(db, "audit.signing.enabled", False)), "signing_note": both("signing_not_available"),
        "is_demo": f.is_demo, "model_version": f.model_version, "calculation_basis": f.calculation_basis,
    }


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def render_export(db: Session, f: AuditWorkingFile, *, lang: str = "en", generated: date | None = None, supplied_documents_only: bool = False) -> str:
    """Watermarked bilingual export (browser prints). Header band EN/AR, page-1 notice, data gaps, footer."""
    generated = generated or dubai_today()
    lbl = status_label(db, f)
    gaps = [g for g in gaps_for(db, f) if g.status != "received"]
    rows = []
    for fig in (f.ai_prepared_content or {}).get("figures", []):
        val = f"AED {fig['value_fils'] / 100:,.2f}" if fig.get("value_fils") is not None else f"{s('gap_n', 'en', n=fig.get('gap') or '?')} / {s('gap_n', 'ar', n=fig.get('gap') or '?')}"
        rows.append(f"<tr><td>{_esc(fig['label']['en'])}</td><td dir='rtl' lang='ar'>{_esc(fig['label']['ar'])}</td><td dir='ltr'><bdi>{_esc(val)}</bdi></td></tr>")
    gap_rows = "".join(f"<tr><td>{g.gap_number}</td><td>{_esc(g.item_en)}<br><span lang='ar' dir='rtl'>{_esc(g.item_ar)}</span></td><td>{_esc(g.why_en)}</td><td>{_esc(g.status)}</td></tr>" for g in gaps)
    incomplete = f.completeness_state == "incomplete"
    rejected = f.status == "rejected"
    band_en = s("export_header", "en", status=lbl["en"]) + (f" · {s('incomplete', 'en')} / {s('incomplete', 'ar')}" if incomplete else "")
    band_ar = s("export_header", "ar", status=lbl["ar"])
    limitation = f"<p class='notice'>{_esc(s('supplied_documents_only', 'en'))} / <span lang='ar' dir='rtl'>{_esc(s('supplied_documents_only', 'ar'))}</span></p>" if supplied_documents_only else ""
    footer = f"{_esc(s('export_footer', 'en', date=generated.isoformat(), n=1, m=1))}<br><span lang='ar' dir='rtl'>{_esc(s('export_footer', 'ar', date=generated.isoformat(), n=1, m=1))}</span>"
    return f"""<!doctype html><html lang="{lang}" dir="{'rtl' if lang == 'ar' else 'ltr'}"><head><meta charset="utf-8"><title>{_esc(s('file_title', lang))} - {_esc(WATERMARK['en'])}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;position:relative}}.wm{{position:fixed;top:40%;left:0;right:0;text-align:center;transform:rotate(-30deg);opacity:.15;font-size:42px;color:#555;pointer-events:none;z-index:0}}
.band{{display:flex;justify-content:space-between;background:#333;color:#fff;padding:8px}}.notice{{border:2px solid #333;padding:8px;margin:12px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #999;padding:4px}}footer{{margin-top:24px;font-size:12px}}</style></head>
<body><div class="wm" aria-hidden="true" data-artifact="watermark"><div>{_esc(WATERMARK['en'])}</div><div lang="ar" dir="rtl">{_esc(WATERMARK['ar'])}</div></div>
<header class="band"><span lang="en" dir="ltr">{_esc(band_en)}{' · Rejected' if rejected else ''}</span><span lang="ar" dir="rtl">{_esc(band_ar)}</span></header>
<p class="notice"><strong>{_esc(s('page1_notice', 'en'))}</strong> / <span lang="ar" dir="rtl">{_esc(s('page1_notice', 'ar'))}</span><br>{_esc(s('fixed_draft_text', 'en'))}<br><span lang="ar" dir="rtl">{_esc(s('fixed_draft_text', 'ar'))}</span></p>{limitation}
<section class="notice"><h2>{_esc(s('data_gaps', 'en'))} / <span lang="ar" dir="rtl">{_esc(s('data_gaps', 'ar'))}</span></h2><table><tr><th>#</th><th>Item</th><th>Why it matters</th><th>Status at export</th></tr>{gap_rows or '<tr><td colspan=4>—</td></tr>'}</table><p>Export date: {generated.isoformat()}</p></section>
<h1>{_esc(s('file_title', 'en'))} / <span lang="ar" dir="rtl">{_esc(s('file_title', 'ar'))}</span></h1>
<p>Period: <bdi dir="ltr">{f.period_start.isoformat()} – {f.period_end.isoformat()}</bdi> · Version <bdi>{f.version_no}</bdi></p>
<table><tr><th>English</th><th>العربية</th><th>Value</th></tr>{''.join(rows)}</table>
<footer>{footer}<br>{_esc(s('no_code_until_signed', 'en'))}</footer></body></html>"""


def k18(db: Session, today: date | None = None) -> dict:
    """Time to prepare audit draft: from period_end to first complete draft (immutable); incomplete reported beside."""
    today = today or dubai_today()
    days, open_ages = [], []
    for f in db.scalars(select(AuditWorkingFile).where(AuditWorkingFile.version_no == 1)):
        if f.period_end > today:
            continue  # nothing computed while the period end is in the future
        if f.first_complete_draft_ready_at:
            days.append((f.first_complete_draft_ready_at.date() - f.period_end).days)
        else:
            open_ages.append((today - f.period_end).days)
    days.sort()
    med = days[len(days) // 2] if days else None
    return {"n": len(days), "median_days": med, "mean_days": round(sum(days) / len(days), 1) if days else None, "incomplete_n": len(open_ages), "incomplete_open_age_days": open_ages}


def k19(db: Session) -> dict:
    """Sign-off status mix: one current version per signature-required deliverable; unsigned-release count must be 0."""
    mix: dict[str, int] = {}
    released_unsigned = 0
    for f in db.scalars(select(AuditWorkingFile).where(AuditWorkingFile.is_current.is_(True), AuditWorkingFile.signature_required.is_(True))):
        mix[f.status] = mix.get(f.status, 0) + 1
    return {"status_mix": mix, "unsigned_release_count": released_unsigned}

