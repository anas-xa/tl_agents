"""Approval compliance monitoring (E6-S4): detective control over the E6-S3 gate.

K23 = submissions with a valid approval record / all submissions x 100 (target 100%; any value below is a
breach; no submissions -> 'No data', never 0% or 100%). K24 = mean hours from request to decision (decided
requests only; no pass/fail until a target is set). Severity 1 stops the pilot approval flow and blocks the wave
exit review until the DET pilot manager and the Qeonix product owner both record a root cause and fix.
Read-back is 'Not available' everywhere in Phase 1. Deterministic: the same records give the same result.

Other modules (DET KPI) import: ``from app.modules.approvals.monitoring import k23, k24``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import utcnow
from app.modules.approvals.models import (
    Approval,
    ApprovalRequest,
    ApprovalStatusEvent,
    ComplianceAlert,
    ComplianceException,
    ComplianceJobRun,
    DelegateApprovalGrant,
    GateDecision,
    ManualFilingRecord,
    SubmissionAttempt,
)
from app.modules.approvals.strings import EXCEPTION_LABELS, FILING_STATE_LABELS, STRINGS
from app.modules.audit.service import record_event
from app.modules.config.service import get_config, set_config

GST = timedelta(hours=4)
K23_DEFINITION = "Submissions with a valid approval, out of all submissions recorded in the period."
DEFAULT_ROUTING = {
    "1": {"case_owner": "det_pilot_manager", "backup": "qeonix_product_owner", "notified": ["det_compliance_lead"]},
    "2": {"case_owner": "qeonix_product_owner", "informed": ["det_pilot_manager"], "notified": ["det_compliance_lead"]},
}
RESOLVER_ROLES = ("det_pilot_manager", "qeonix_product_owner")


# --- periods (Asia/Dubai calendar) ---------------------------------------------------------------


def period_bounds(period: Any) -> tuple[datetime | None, datetime | None]:
    """Accepts None/'all', 'YYYY', 'YYYY-MM', 'YYYY-Qn', 'YYYY-MM-DD..YYYY-MM-DD', (start, end) or
    {'start','end'}; Dubai-local dates -> naive UTC bounds [start, end)."""
    if period in (None, "", "all"):
        return None, None
    start: date
    end: date
    if isinstance(period, dict):
        start, end = _d(period["start"]), _d(period["end"])
    elif isinstance(period, (tuple, list)):
        start, end = _d(period[0]), _d(period[1])
    else:
        p = str(period)
        if m := re.fullmatch(r"(\d{4})-Q([1-4])", p):
            y, q = int(m[1]), int(m[2])
            start = date(y, 3 * q - 2, 1)
            end = (date(y + 1, 1, 1) if q == 4 else date(y, 3 * q + 1, 1)) - timedelta(days=1)
        elif m := re.fullmatch(r"(\d{4})-(\d{2})", p):
            y, mo = int(m[1]), int(m[2])
            start = date(y, mo, 1)
            end = (date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)) - timedelta(days=1)
        elif re.fullmatch(r"\d{4}", p):
            start, end = date(int(p), 1, 1), date(int(p), 12, 31)
        elif ".." in p:
            a, b = p.split("..", 1)
            start, end = _d(a), _d(b)
        else:
            raise ValidationFailed("unknown period format", reason_code="PERIOD_INVALID")
    return datetime.combine(start, time.min) - GST, datetime.combine(end + timedelta(days=1), time.min) - GST


def _d(v: Any) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else (v.date() if isinstance(v, datetime) else date.fromisoformat(str(v)))


def _in(at: datetime, lo: datetime | None, hi: datetime | None) -> bool:
    return (lo is None or at >= lo) and (hi is None or at < hi)


# --- submissions and matching ---------------------------------------------------------------------


def submissions(db: Session, period: Any = None, *, company_id: str | None = None, tax_type: str | None = None, approver_role: str | None = None) -> list[dict]:
    lo, hi = period_bounds(period)
    out = []
    for r in db.scalars(select(ManualFilingRecord).where(ManualFilingRecord.state.in_(("filed_outside_self_declared", "filed_outside_values_differ"))).order_by(ManualFilingRecord.recorded_at, ManualFilingRecord.id)):
        out.append({"ref": r.id, "kind": "manual_filing", "company_id": r.company_id, "tax_type": r.tax_type, "at": r.recorded_at, "approval_id": r.approval_id, "data_version_hash": r.data_version_hash, "self_reported": True, "is_demo": r.is_demo})
    for a in db.scalars(select(SubmissionAttempt).where(SubmissionAttempt.is_demo.is_(False)).order_by(SubmissionAttempt.send_time, SubmissionAttempt.id)):
        out.append({"ref": a.id, "kind": "attempt", "company_id": a.company_id, "tax_type": a.tax_type, "at": a.send_time, "approval_id": a.approval_id, "data_version_hash": a.data_version_hash, "self_reported": False, "is_demo": False})
    rows = []
    for s in out:
        if not _in(s["at"], lo, hi) or (company_id and s["company_id"] != company_id) or (tax_type and s["tax_type"] != tax_type):
            continue
        a = db.get(Approval, s["approval_id"]) if s["approval_id"] else None
        s["approver_role"] = _role_key(a)
        if approver_role and s["approver_role"] != approver_role:
            continue
        rows.append(s)
    return rows


def _role_key(a: Approval | None) -> str | None:
    if a is None:
        return None
    if a.capacity == "delegate":
        return "delegate"
    return "owner_abroad" if a.display_role == "Owner abroad" else ("authorised_signatory" if a.capacity == "authorised_signatory" else "owner")


def match(db: Session, sub: dict) -> dict:
    """Valid only if an approval exists, the approver was entitled at that time (grant history), the approved data
    version equals the submitted one and the approval came before the submission and was still in force."""
    a = db.get(Approval, sub["approval_id"]) if sub.get("approval_id") else None
    at = sub["at"]
    reason, sev = None, None
    if a is None or a.decision != "approve":
        reason, sev = "no_valid_approval_found", 1
    elif a.data_version_hash != sub.get("data_version_hash"):
        reason, sev = "wrong_version", 1
    elif a.decided_at > at:
        reason, sev = "approval_after_submission", 1
    elif a.valid_until is not None and at > a.valid_until:
        reason, sev = "expired", 1
    else:
        events = list(db.scalars(select(ApprovalStatusEvent).where(ApprovalStatusEvent.approval_id == a.id, ApprovalStatusEvent.at <= at).order_by(ApprovalStatusEvent.at, ApprovalStatusEvent.id)))
        last = events[-1].to_status if events else "active"
        if last in ("withdrawn", "suspended"):
            reason, sev = ("approver_not_entitled" if a.capacity == "delegate" else "withdrawn"), 1
        elif last == "superseded":
            reason, sev = "wrong_version", 1
        elif last == "expired":
            reason, sev = "expired", 1
        elif last == "pending_joint" or (not events and a.status == "pending_joint"):
            reason, sev = "no_valid_approval_found", 1
        elif a.capacity == "delegate":
            g = db.get(DelegateApprovalGrant, (a.delegation_basis or {}).get("grant_id")) if a.delegation_basis else None
            if g is None or g.created_at > a.decided_at or (g.revoked_at is not None and g.revoked_at <= a.decided_at):
                reason, sev = "approver_not_entitled", 1
        if reason is None:
            missing = [f for f, v in (("identity", a.approver_uuid and a.assurance_level), ("authority_evidence", a.authority_evidence_ref or a.delegation_basis), ("return_hash", a.data_version_hash), ("rule_version", a.rule_version_ids), ("timestamp", a.decided_at)) if not v]
            if missing:
                reason, sev = "record_incomplete", 2
    valid = sev is None or sev == 2  # severity 2: the approval itself is valid, the record is incomplete
    return {"submission_ref": sub["ref"], "kind": sub["kind"], "company_id": sub["company_id"], "tax_type": sub["tax_type"], "at": sub["at"].isoformat(), "approval_id": sub.get("approval_id"), "approver_role": sub.get("approver_role"), "match_status": "valid" if sev is None else "exception", "valid_approval": valid, "exception_reason": reason, "severity": sev, "self_reported": sub["self_reported"], "read_back_status": STRINGS["not_available"]["en"]}


# --- KPIs ----------------------------------------------------------------------------------------


def k23(db: Session, period: Any = None, **filters: Any) -> dict:
    subs = submissions(db, period, **filters)
    matches = [match(db, s) for s in subs]
    den = len(matches)
    num = sum(1 for m in matches if m["valid_approval"])
    lo, hi = period_bounds(period)
    gates = [g for g in db.scalars(select(GateDecision)) if _in(g.at, lo, hi) and (not filters.get("company_id") or g.company_id == filters["company_id"]) and (not filters.get("tax_type") or g.tax_type == filters["tax_type"])]
    base = {"kpi": "K23", "name": "submissions with a valid approval", "definition": K23_DEFINITION, "target_pct": float(get_config(db, "approval.k23_target_pct", 100)), "numerator": num, "denominator": den, "self_reported_count": sum(1 for m in matches if m["self_reported"]), "release_approvals": sum(1 for g in gates if g.path == "manual_release" and g.outcome == "pass"), "blocked_attempts": sum(1 for g in gates if g.outcome == "block"), "read_back": STRINGS["not_available"]["en"], "period": period if isinstance(period, str) or period is None else str(period)}
    if den == 0:
        return base | {"value_pct": None, "display": "No data", "status": "no_data", "breach": False, "breach_count": 0, "text": STRINGS["k23_no_data"]}
    pct = round(num * 100.0 / den, 1)
    breach = pct < base["target_pct"]
    return base | {"value_pct": pct, "display": f"{pct:.1f}%", "status": "breach" if breach else "pass", "breach": breach, "breach_count": den - num, "text": {k: v.replace("{x}", str(den - num)).replace("{y}", str(den)) for k, v in STRINGS["k23_breach"].items()} if breach else None}


def _decision_approval(db: Session, req: ApprovalRequest) -> Approval | None:
    rows = [a for a in db.scalars(select(Approval).where(Approval.request_id == req.id).order_by(Approval.decided_at)) if a.status != "pending_joint"]
    return rows[-1] if rows else None


def k24(db: Session, period: Any = None, *, company_id: str | None = None, tax_type: str | None = None, approver_role: str | None = None, now: datetime | None = None) -> dict:
    lo, hi = period_bounds(period)
    now = now or utcnow()
    decided, open_ages = [], []
    for req in db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at, ApprovalRequest.id)):
        if (company_id and req.company_id != company_id) or (tax_type and req.return_type != tax_type):
            continue
        if req.decided_at is not None and req.status in ("decided", "in_preparation"):
            if not _in(req.decided_at, lo, hi):
                continue
            a = _decision_approval(db, req)
            role = _role_key(a) or "owner"
            if approver_role and role != approver_role:
                continue
            decided.append({"hours": (req.decided_at - req.created_at).total_seconds() / 3600.0, "role": role, "tax_type": req.return_type})
        elif req.status == "open" and _in(req.created_at, lo, hi):
            open_ages.append(round((now - req.created_at).total_seconds() / 3600.0, 1))
    target = get_config(db, "approval.k24_target_hours", None)

    def mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    groups: dict[str, list[float]] = {}
    for d in decided:
        key = {"owner": "owner_in_uae", "authorised_signatory": "owner_in_uae", "owner_abroad": "owner_abroad", "delegate": "delegate"}[d["role"]]
        groups.setdefault(key, []).append(d["hours"])
    by_type: dict[str, list[float]] = {}
    for d in decided:
        by_type.setdefault(d["tax_type"], []).append(d["hours"])
    out = {"kpi": "K24", "name": "average hours to decide on an approval request", "decided_count": len(decided), "mean_hours": mean([d["hours"] for d in decided]), "undecided_count": len(open_ages), "undecided_ages_hours": open_ages, "waiting_text": {"en": f"Waiting for a decision: {len(open_ages)}", "ar": f"بانتظار القرار: {len(open_ages)}"}, "breakdown": {k: mean(v) for k, v in sorted(groups.items())}, "by_document_type": {k: mean(v) for k, v in sorted(by_type.items())}, "target_hours": target, "pass": None, "target_text": STRINGS["k24_no_target"] if target is None else None}
    if not decided:
        out |= {"display": "No data", "text": STRINGS["k24_no_data"]}
    else:
        out["display"] = f"{out['mean_hours']:.1f}"
        if target is not None:
            out["pass"] = out["mean_hours"] <= float(target)
    return out


# --- job, exceptions, alerts, pilot stop ----------------------------------------------------------


def _routing(db: Session) -> dict:
    return get_config(db, "approval.alert_routing", DEFAULT_ROUTING) or DEFAULT_ROUTING


def _raise_exception(db: Session, m: dict) -> ComplianceException:
    route = _routing(db)[str(m["severity"])]
    exc = ComplianceException(submission_ref=m["submission_ref"], submission_kind=m["kind"], company_id=m["company_id"], approval_id=m["approval_id"], reason_code=m["exception_reason"], severity=m["severity"], case_owner_role=route["case_owner"], recipients=[route["case_owner"], *([route["backup"]] if route.get("backup") else []), *route.get("informed", []), *route.get("notified", [])])
    db.add(exc)
    db.flush()
    record_event(db, event_type="EXCEPTION_RAISED", category="approval", outcome="exception", reason_code=m["exception_reason"].upper(), company_id=m["company_id"], subject_type="compliance_exception", subject_id=exc.id, details={"severity": m["severity"], "submission_ref": m["submission_ref"], "case_owner": route["case_owner"]})
    channels = get_config(db, "approval.alert_channels", ["in_portal", "role_mailbox_email"])
    for role, kind in [(route["case_owner"], "case_owner"), *([(route["backup"], "backup")] if route.get("backup") else []), *[(r, "informed") for r in route.get("informed", [])], *[(r, "notified") for r in route.get("notified", [])]]:
        db.add(ComplianceAlert(exception_id=exc.id, alert_type="approval_exception", severity=m["severity"], recipient_role=role, kind=kind, channels=channels))
        record_event(db, event_type="ALERT_SENT", category="approval", company_id=m["company_id"], subject_type="compliance_exception", subject_id=exc.id, details={"to_role": role, "kind": kind, "severity": m["severity"], "channels": channels})
    if m["exception_reason"] in ("no_valid_approval_found", "approver_not_entitled", "wrong_version", "approval_after_submission", "expired", "withdrawn"):
        record_event(db, event_type="CONTROL_FAILURE_INCIDENT_RAISED", category="approval", outcome="exception", reason_code=m["exception_reason"].upper(), company_id=m["company_id"], subject_type="compliance_exception", subject_id=exc.id, details={"to_role": "qeonix_product_owner"})
    if m["severity"] == 1:
        pilot_stop(db, exc)
    return exc


def pilot_stop(db: Session, exc: ComplianceException) -> None:
    """Severity 1: switch off the return-pack approval flow for all pilot companies; no new approval requests and
    the wave exit review is blocked until root cause and fix are recorded."""
    if get_config(db, "approval.flow_enabled", True):
        set_config(db, "approval.flow_enabled", False, changed_by="system:approval_compliance", change_reason=f"severity 1 exception {exc.id}")
    if not get_config(db, "approval.wave_exit.blocked", False):
        set_config(db, "approval.wave_exit.blocked", True, changed_by="system:approval_compliance", change_reason=f"severity 1 exception {exc.id}")
    record_event(db, event_type="PILOT_STOP_APPLIED", category="config", outcome="info", reason_code="SEVERITY_1", subject_type="compliance_exception", subject_id=exc.id)


def run_compliance_job(db: Session, *, job: str = "daily_k23") -> dict:
    """Daily match + K23 (weekly K24). Read-only over the records; raises exceptions and alerts once each."""
    try:
        matches = [match(db, s) for s in submissions(db)]
        raised = []
        for m in matches:
            if m["exception_reason"] is None:
                continue
            if db.scalar(select(ComplianceException).where(ComplianceException.submission_ref == m["submission_ref"], ComplianceException.reason_code == m["exception_reason"]).limit(1)):
                continue
            raised.append(_raise_exception(db, m).id)
        result = {"k23": k23(db), "k24": k24(db), "exceptions_raised": raised}
        db.add(ComplianceJobRun(job=job, success=True, result={"k23": result["k23"]["display"], "raised": len(raised)}))
        record_event(db, event_type="COMPLIANCE_JOB_RUN", category="system", outcome="success", details={"job": job, "raised": len(raised)})
        db.flush()
        return result
    except Exception:
        db.add(ComplianceJobRun(job=job, success=False))
        record_event(db, event_type="COMPLIANCE_JOB_RUN", category="system", outcome="failed", details={"job": job})
        db.flush()
        raise


def wave_exit_blocked(db: Session) -> bool:
    """A wave cannot close with any unresolved case (severity 1 or 2)."""
    return db.scalar(select(ComplianceException).where(ComplianceException.review_status != "resolved").limit(1)) is not None


def review_exception(db: Session, principal: Any, exc_id: str, *, status: str, note_ref: str | None = None) -> ComplianceException:
    """Reviewer notes and review status only; underlying records are never altered. Audited with identity."""
    exc = db.get(ComplianceException, exc_id)
    if exc is None:
        raise NotFound("exception not found", reason_code="NOT_FOUND")
    if status not in ("open", "acknowledged", "contained"):
        raise ValidationFailed("reviewers set open, acknowledged or contained; case owners record the outcome", reason_code="VALIDATION_FAILED")
    exc.review_status = status
    if status == "acknowledged" and exc.acknowledged_at is None:
        exc.acknowledged_at = utcnow()
    if note_ref:
        exc.reviewer_notes = [*(exc.reviewer_notes or []), {"note": note_ref[:500], "by": principal.actor_key, "at": utcnow().isoformat()}]
    record_event(db, event_type="CASE_STATUS_CHANGED", category="approval", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="compliance_exception", subject_id=exc.id, details={"to": status})
    db.flush()
    return exc


def record_root_cause(db: Session, principal: Any, exc_id: str, *, root_cause: str, fix: str) -> ComplianceException:
    """Case owners record outcome and corrective action. Severity 1 needs both the DET pilot manager and the
    Qeonix product owner; when every severity-1 case has both, the approval flow is switched back on."""
    roles = [r for r in RESOLVER_ROLES if r in (principal.staff_roles or [])]
    if not roles:
        raise Forbidden("Only the DET pilot manager or the Qeonix product owner records the root cause and fix.", reason_code="NO_PERMISSION")
    if not root_cause.strip() or not fix.strip():
        raise ValidationFailed("Root cause and fix are both required.", reason_code="REASON_REQUIRED")
    exc = db.get(ComplianceException, exc_id)
    if exc is None:
        raise NotFound("exception not found", reason_code="NOT_FOUND")
    rc = dict(exc.root_cause or {})
    for r in roles:
        rc[r] = {"root_cause": root_cause.strip()[:1000], "fix": fix.strip()[:1000], "by": principal.actor_key, "at": utcnow().isoformat()}
    exc.root_cause = rc
    exc.corrective_action = {r: rc[r]["fix"] for r in rc}
    needed = RESOLVER_ROLES if exc.severity == 1 else ("qeonix_product_owner",)
    if all(r in rc for r in needed):
        exc.review_status, exc.resolved_at = "resolved", utcnow()
    record_event(db, event_type="CASE_STATUS_CHANGED", category="approval", actor_key=principal.actor_key, actor_role=roles[0], subject_type="compliance_exception", subject_id=exc.id, details={"root_cause_recorded_by": sorted(rc), "status": exc.review_status})
    db.flush()
    if not db.scalar(select(ComplianceException).where(ComplianceException.severity == 1, ComplianceException.review_status != "resolved").limit(1)):
        if not get_config(db, "approval.flow_enabled", True):
            set_config(db, "approval.flow_enabled", True, changed_by="system:approval_compliance", change_reason="root cause and fix recorded by the DET pilot manager and the Qeonix product owner")
    if not wave_exit_blocked(db) and get_config(db, "approval.wave_exit.blocked", False):
        set_config(db, "approval.wave_exit.blocked", False, changed_by="system:approval_compliance", change_reason="all exception cases resolved")
    db.flush()
    return exc


def exception_dict(e: ComplianceException) -> dict:
    lab = EXCEPTION_LABELS.get(e.reason_code, {"en": e.reason_code, "ar": e.reason_code})
    return {"exception_id": e.id, "submission_ref": e.submission_ref, "kind": e.submission_kind, "company_id": e.company_id, "approval_id": e.approval_id, "reason_code": e.reason_code, "reason_label": {"en": lab["en"], "ar": lab["ar"]}, "severity": e.severity, "case_owner_role": e.case_owner_role, "recipients": e.recipients, "review_status": e.review_status, "root_cause_recorded_by": sorted((e.root_cause or {}).keys()), "created_at": e.created_at.isoformat(), "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None, "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None, "notes_count": len(e.reviewer_notes or [])}


def compliance_view(db: Session, *, period: Any = None, company_id: str | None = None, tax_type: str | None = None, approver_role: str | None = None) -> dict:
    """SC15 reviewer / SC14 DET tab data: references and codes only, no financial figures."""
    f = {"company_id": company_id, "tax_type": tax_type, "approver_role": approver_role}
    subs = [match(db, s) for s in submissions(db, period, **f)]
    lo, hi = period_bounds(period)
    blocked = [{"gate_id": g.id, "path": g.path, "reason_code": g.reason_code, "caller_type": g.caller_type, "tax_type": g.tax_type, "company_id": g.company_id, "at": g.at.isoformat()} for g in db.scalars(select(GateDecision).where(GateDecision.outcome == "block").order_by(GateDecision.at.desc())) if _in(g.at, lo, hi) and (not company_id or g.company_id == company_id) and (not tax_type or g.tax_type == tax_type)]
    last = db.scalar(select(ComplianceJobRun).where(ComplianceJobRun.success.is_(True)).order_by(ComplianceJobRun.ran_at.desc()).limit(1))
    stale_h = int(get_config(db, "approval.compliance_job.stale_hours", 24))
    excs = [e for e in db.scalars(select(ComplianceException).order_by(ComplianceException.created_at.desc())) if (not company_id or e.company_id == company_id)]
    return {
        "k23": k23(db, period, **f), "k24": k24(db, period, **f), "submissions": subs, "blocked_attempts": blocked, "exceptions": [exception_dict(e) for e in excs],
        "job": {"last_success_at": last.ran_at.isoformat() if last else None, "stale": last is None or (utcnow() - last.ran_at) > timedelta(hours=stale_h), "schedule": get_config(db, "approval.compliance_job.schedule", {"k23": "daily", "k24": "weekly"})},
        "flow_enabled": bool(get_config(db, "approval.flow_enabled", True)), "wave_exit_blocked": wave_exit_blocked(db) or bool(get_config(db, "approval.wave_exit.blocked", False)),
        "read_back": {"status": STRINGS["not_available"], "text": STRINGS["read_back_na"]}, "read_only": True,
        "filters": {"period": period, **f}, "approver_roles": ["owner", "owner_abroad", "authorised_signatory", "delegate"], "tax_types": ["vat", "ct"],
    }


# --- owner / delegate approval history (SC7 section) -------------------------------------------


def history_rows(db: Session, company_id: str) -> list[dict]:
    from app.modules.approvals.service import approval_state, filing_status

    rows = []
    reqs = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == company_id).order_by(ApprovalRequest.created_at.desc())))
    excs = {e.submission_ref: e for e in db.scalars(select(ComplianceException).where(ComplianceException.company_id == company_id))}
    for req in reqs:
        a = _decision_approval(db, req)
        fil = filing_status(db, req)
        chip, attention = "waiting", None
        if a is not None and a.decision == "approve":
            ok, cause = (True, None) if fil["state"] != "not_filed" else approval_state(db, a)
            chip = "approved" if ok else ("expired" if cause == "approval_expired" else "not_approved")
            if not ok:
                attention = {"data_changed_since_approval": EXCEPTION_LABELS["wrong_version"]["owner_en"], "approval_expired": STRINGS["expired_pack_label"]["en"], "approver_no_longer_has_rights": EXCEPTION_LABELS["approver_not_entitled"]["owner_en"]}.get(cause or "", None)
        elif a is not None:
            chip = "not_approved"
        elif req.status in ("expired", "superseded", "blocked"):
            chip = "expired" if req.status == "expired" else "not_approved"
        rec_id = fil.get("record_id")
        if rec_id and rec_id in excs:
            attention = EXCEPTION_LABELS.get(excs[rec_id].reason_code, {}).get("owner_en", attention)
        rows.append({
            "request_id": req.id, "return_type": req.return_type, "period_id": req.period_id, "status_chip": chip, "request_status": req.status,
            "approved_by": {"name": a.approver_name, "role": a.display_role, "delegation_basis": a.delegation_basis} if a is not None and a.decision == "approve" else None,
            "decided_at": a.decided_at.isoformat() if a else None, "data_version": {"prepared_on": req.created_at.isoformat(), "version": req.pack_version, "short_hash": req.draft_content_hash[:8]},
            "submission_status": fil["state"], "submission_label": FILING_STATE_LABELS.get(fil["state"], FILING_STATE_LABELS["not_filed"]), "submitted_by": fil.get("submitted_by"),
            "needs_attention": attention, "is_demo": req.is_demo,
        })
    rows.sort(key=lambda r: (r["needs_attention"] is None,))
    return rows
