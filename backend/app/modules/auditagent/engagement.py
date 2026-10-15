"""E7-S4 licensed-auditor review (SC13): engagements, firewall + independence + register snapshot at assignment,
UAE PASS re-auth for review acts, 'Record review' (signing stays OFF), coded returns, 'signed outside platform',
reminders 14/7/2 days and escalation after 3 working days of inactivity, signature-void versioning.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import dubai_date, dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.auditagent import workfile as wf
from app.modules.auditagent.models import (
    REJECTION_CODES,
    AuditorReviewRecord,
    AuditWorkingFile,
    Engagement,
    ExceptionFlag,
    ReauthAssertion,
    RegisterCheck,
    RegisterSnapshot,
    ReturnRecord,
    SignedOutsideRecord,
    SignRecord,
)
from app.modules.auditagent.strings import both
from app.modules.config.service import get_config

DEFAULT_MOCK_REGISTER = [
    {"register_ref": "AUD-2201", "name": "Layla Haddad", "licence_number": "MOE-AUD-2201", "status": "active", "firm": "Haddad & Partners Auditing", "signing_authority": True, "valid_to": "2027-12-31"},
    {"register_ref": "AUD-9001", "name": "Demo Suspended", "licence_number": "MOE-AUD-9001", "status": "suspended", "firm": "Demo Firm", "signing_authority": True, "valid_to": "2027-12-31"},
    {"register_ref": "AUD-9002", "name": "Demo Expired", "licence_number": "MOE-AUD-9002", "status": "expired", "firm": "Demo Firm", "signing_authority": True, "valid_to": "2025-12-31"},
    {"register_ref": "AUD-9003", "name": "Demo Struck Off", "licence_number": "MOE-AUD-9003", "status": "struck_off", "firm": "Demo Firm", "signing_authority": True, "valid_to": "2027-12-31"},
    {"register_ref": "AUD-9004", "name": "Demo Ambiguous A", "licence_number": "MOE-AUD-9004A", "status": "active", "firm": "Demo Firm", "signing_authority": True, "valid_to": "2027-12-31"},
    {"register_ref": "AUD-9004", "name": "Demo Ambiguous B", "licence_number": "MOE-AUD-9004B", "status": "active", "firm": "Other Firm", "signing_authority": True, "valid_to": "2027-12-31"},
    {"register_ref": "AUD-9005", "name": "Demo No Authority", "licence_number": "MOE-AUD-9005", "status": "active", "firm": "Demo Firm", "signing_authority": False, "valid_to": "2027-12-31"},
]
STATUS_OUTCOME = {"suspended": "blocked_suspended", "expired": "blocked_expired", "struck_off": "blocked_struck_off", "unlisted": "blocked_unlisted"}


class RegisterUnreachable(RuntimeError):
    pass


def _cfg(db: Session, key: str, default: Any) -> Any:
    v = get_config(db, key, default)
    return default if v is None else v


# --- register (Ministry of Economy mock) ----------------------------------------------------------------------


def register_ref_for(db: Session, identity_uuid: str) -> str | None:
    """StaffRole.entitlement_ref holds the register reference (e.g. 'MoE auditor register ref AUD-2201')."""
    from app.modules.identity.models import StaffRole

    row = db.scalar(select(StaffRole).where(StaffRole.identity_uuid == identity_uuid, StaffRole.role == "licensed_auditor", StaffRole.status == "active").limit(1))
    if row is None or not row.entitlement_ref:
        return None
    m = re.search(r"[A-Z]{2,5}-\d{3,6}", row.entitlement_ref)
    return m.group(0) if m else row.entitlement_ref.strip()


def fetch_register_snapshot(db: Session, *, loaded_by: str = "register refresh (scheduled)") -> RegisterSnapshot:
    """Load a dated snapshot from the mock register with retries (2 s, 10 s, 30 s; no sleeping in the mock)."""
    retries = list(_cfg(db, "auditagent.register.retries_seconds", [2, 10, 30]))
    attempts = 0
    for _ in range(len(retries) + 1):
        attempts += 1
        if not _cfg(db, "auditagent.register.simulate_unreachable", False):
            snap = RegisterSnapshot(loaded_by=loaded_by, entries=list(_cfg(db, "auditagent.register.mock_entries", DEFAULT_MOCK_REGISTER)))
            db.add(snap)
            db.flush()
            record_event(db, event_type="REGISTER_SNAPSHOT_LOADED", category="sign_off", subject_type="register_snapshot", subject_id=snap.id, details={"entries": len(snap.entries), "attempts": attempts})
            return snap
    record_event(db, event_type="REGISTER_UNREACHABLE", category="sign_off", outcome="failed", reason_code="REGISTER_UNREACHABLE", details={"attempts": attempts, "backoff_seconds": retries})
    raise RegisterUnreachable("auditor register unreachable")


def latest_snapshot(db: Session) -> RegisterSnapshot | None:
    return db.scalar(select(RegisterSnapshot).order_by(RegisterSnapshot.loaded_at.desc()).limit(1))


def check_register(db: Session, identity_uuid: str, *, engagement_id: str | None = None, purpose: str = "assignment", now: datetime | None = None) -> RegisterCheck:
    """Fail closed: unreachable, stale snapshot (> 24 h), unlisted, ambiguous, suspended, expired, struck off -> blocked."""
    now = now or utcnow()
    ref = register_ref_for(db, identity_uuid)
    max_age = timedelta(hours=int(_cfg(db, "auditagent.register.snapshot_max_age_hours", 24)))
    snap = latest_snapshot(db)
    attempts = 1
    if snap is None or now - snap.loaded_at > max_age:
        try:
            snap = fetch_register_snapshot(db)
        except RegisterUnreachable:
            attempts = 1 + len(_cfg(db, "auditagent.register.retries_seconds", [2, 10, 30]))
            outcome = "blocked_unreachable" if snap is None else "blocked_stale_snapshot"
            return _store_check(db, identity_uuid, engagement_id, ref, snap, outcome, purpose, attempts)
    entries = [e for e in (snap.entries or []) if ref and e.get("register_ref") == ref]
    if not entries:
        outcome = "blocked_unlisted"
    elif len(entries) > 1:
        outcome = "blocked_ambiguous"  # routed to the compliance reviewer, never auto-picked
    else:
        e = entries[0]
        outcome = STATUS_OUTCOME.get(e.get("status", "unlisted"), "allowed")
        if outcome == "allowed" and e.get("valid_to") and date.fromisoformat(e["valid_to"]) < dubai_date(now):
            outcome = "blocked_expired"
        if outcome == "allowed" and purpose == "sign" and not e.get("signing_authority"):
            outcome = "blocked_no_signing_authority"
    return _store_check(db, identity_uuid, engagement_id, ref, snap, outcome, purpose, attempts)


def _store_check(db: Session, uuid: str, engagement_id: str | None, ref: str | None, snap: RegisterSnapshot | None, outcome: str, purpose: str, attempts: int) -> RegisterCheck:
    rc = RegisterCheck(engagement_id=engagement_id, auditor_identity_uuid=uuid, register_ref=ref, snapshot_id=snap.id if snap else None, snapshot_loaded_at=snap.loaded_at if snap else None, outcome=outcome, attempts=attempts, purpose=purpose)
    db.add(rc)
    db.flush()
    record_event(db, event_type="REGISTER_CHECK", category="sign_off", outcome="success" if outcome == "allowed" else "refused", reason_code=None if outcome == "allowed" else outcome.upper(), identity_uuid=uuid, actor_role="licensed_auditor", subject_type="engagement", subject_id=engagement_id, details={"outcome": outcome, "snapshot_id": rc.snapshot_id, "purpose": purpose, "routed_to": "compliance_reviewer" if outcome == "blocked_ambiguous" else None})
    return rc


def register_check_dict(rc: RegisterCheck | None) -> dict | None:
    if rc is None:
        return None
    return {"id": rc.id, "outcome": rc.outcome, "snapshot_id": rc.snapshot_id, "snapshot_loaded_at": rc.snapshot_loaded_at.isoformat() if rc.snapshot_loaded_at else None, "checked_at": rc.checked_at.isoformat(), "register_ref": rc.register_ref, "purpose": rc.purpose,
            "text": {"en": f"Register check: matched on {rc.checked_at.date().isoformat()}, source {rc.snapshot_id}", "ar": f"فحص السجل: تمت المطابقة بتاريخ {rc.checked_at.date().isoformat()}، المصدر {rc.snapshot_id}"} if rc.outcome == "allowed" else (both("register_unreachable") if rc.outcome in ("blocked_unreachable", "blocked_stale_snapshot") else both("licence_not_found") if rc.outcome == "blocked_unlisted" else both("signing_blocked"))}


# --- engagements -------------------------------------------------------------------------------------------


def _staff_name(db: Session, uuid: str) -> str:
    from app.modules.identity.models import Identity

    ident = db.get(Identity, uuid)
    return ident.display_name if ident else uuid


def create_engagement(db: Session, *, company_id: str, auditor_uuid: str, assigned_by: str, firm_name: str | None = None, engagement_manager: str | None = None, review_deadline: date | None = None, actor_key: str | None = None, is_demo: bool = False) -> Engagement:
    """Step 1: pending engagement + firewall evaluation from DET records (refuse on hit)."""
    from app.modules.identity.models import StaffRole

    if db.scalar(select(StaffRole).where(StaffRole.identity_uuid == auditor_uuid, StaffRole.role == "licensed_auditor", StaffRole.status == "active")) is None:
        raise ValidationFailed("the person is not an active licensed auditor on the staff register", reason_code="NOT_LICENSED_AUDITOR")
    f = wf.current_file(db, company_id)
    fallback = not engagement_manager
    eng = Engagement(company_id=company_id, working_file_id=f.id if f else None, auditor_identity_uuid=auditor_uuid, auditor_name=_staff_name(db, auditor_uuid), register_ref=register_ref_for(db, auditor_uuid), firm_name=firm_name, engagement_manager=engagement_manager or "DET pilot manager queue", engagement_manager_is_fallback=fallback, assigned_by=assigned_by, review_deadline=review_deadline, status="not_assigned", is_demo=is_demo)
    db.add(eng)
    db.flush()
    fw = _firewall(db, eng)
    if fw is not None and fw.result == "conflict_found":
        record_event(db, event_type="ASSIGNMENT_REFUSED", category="access", outcome="refused", reason_code="FIREWALL_CONFLICT", actor_key=actor_key, company_id=company_id, subject_type="engagement", subject_id=eng.id)
        raise Forbidden("Assignment refused: a conflict was found in DET records.", reason_code="FIREWALL_CONFLICT", details={"engagement_id": eng.id})
    record_event(db, event_type="ASSIGNMENT_CHANGED", category="access", actor_key=actor_key, company_id=company_id, subject_type="engagement", subject_id=eng.id, details={"step": "created", "auditor_key_present": True})
    return eng


def _firewall(db: Session, eng: Engagement):
    try:
        from app.modules.delegates.service import evaluate_firewall
    except ImportError:  # pragma: no cover
        return None
    rec = evaluate_firewall(db, eng.auditor_identity_uuid, eng.company_id, eng.id, firm=eng.firm_name)
    eng.firewall_record_id = rec.id
    return rec


def firewall_record(db: Session, eng: Engagement):
    try:
        from app.modules.delegates.models import FirewallRecord
    except ImportError:  # pragma: no cover
        return None
    return db.scalar(select(FirewallRecord).where(FirewallRecord.engagement_id == eng.id, FirewallRecord.auditor_identity_uuid == eng.auditor_identity_uuid))


def declare_independence(db: Session, principal: Any, eng: Engagement) -> Any:
    from app.modules.delegates.service import declare_independence as _declare

    if principal.identity_uuid != eng.auditor_identity_uuid:
        raise Forbidden("This engagement is not assigned to you.", reason_code="NOT_ASSIGNED")
    rec = _declare(db, principal, eng.id)
    eng.last_activity_at = utcnow()
    return rec


def activate_engagement(db: Session, eng: Engagement, *, actor_key: str | None = None, now: datetime | None = None) -> Engagement:
    """Step 2: requires the firewall result, a recorded independence declaration and a register snapshot <= 24 h."""
    from app.modules.delegates.service import firewall_clear

    fw = _firewall(db, eng)
    if fw is None or fw.result == "conflict_found":
        raise Forbidden("Assignment refused: a conflict was found in DET records.", reason_code="FIREWALL_CONFLICT")
    if not fw.independence_declared_at:
        raise Conflict("The auditor's independence declaration is required before assignment.", reason_code="INDEPENDENCE_DECLARATION_REQUIRED")
    if not firewall_clear(db, eng.id, eng.auditor_identity_uuid):
        raise Forbidden("Assignment refused by the firewall.", reason_code="FIREWALL_NOT_CLEAR")
    rc = check_register(db, eng.auditor_identity_uuid, engagement_id=eng.id, purpose="assignment", now=now)
    eng.register_check_id = rc.id
    if rc.outcome != "allowed":
        raise Forbidden("Assignment refused: the licence could not be confirmed on a current register snapshot.", reason_code=rc.outcome.upper(), details={"outcome": rc.outcome})
    eng.status = "awaiting_review"
    eng.assigned_at = eng.last_activity_at = utcnow()
    f = wf.current_file(db, eng.company_id)
    if f is not None:
        eng.working_file_id, f.engagement_id = f.id, eng.id
    record_event(db, event_type="ASSIGNMENT_CHANGED", category="access", actor_key=actor_key, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"step": "activated", "register_check": rc.id, "firewall": fw.result})
    db.flush()
    return eng


def get_engagement(db: Session, engagement_id: str) -> Engagement:
    eng = db.get(Engagement, engagement_id)
    if eng is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    return eng


def require_assigned(db: Session, principal: Any, engagement_id: str) -> Engagement:
    """Licensed auditors see only assigned engagements; unassigned opens are denied and logged."""
    eng = db.get(Engagement, engagement_id)
    if eng is None or (eng.auditor_identity_uuid != principal.identity_uuid and not principal.has_staff("qeonix_audit_ops")):
        record_event(db, event_type="UNASSIGNED_ACCESS_DENIED", category="access", outcome="refused", reason_code="NOT_ASSIGNED", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="engagement", subject_id=engagement_id)
        raise Forbidden("This engagement is not assigned to you.", reason_code="NOT_ASSIGNED")
    return eng


def auditor_engagement_for_company(db: Session, identity_uuid: str, company_id: str) -> Engagement | None:
    return db.scalar(select(Engagement).where(Engagement.company_id == company_id, Engagement.auditor_identity_uuid == identity_uuid, Engagement.status.not_in(("not_assigned",))).order_by(Engagement.assigned_at.desc()).limit(1))


def list_for(db: Session, principal: Any) -> list[Engagement]:
    stmt = select(Engagement).where(Engagement.status != "not_assigned")
    if not principal.has_staff("qeonix_audit_ops"):
        stmt = stmt.where(Engagement.auditor_identity_uuid == principal.identity_uuid)
    return list(db.scalars(stmt.order_by(Engagement.assigned_at.desc())))


def evidence_mode(db: Session, eng: Engagement) -> str:
    """'evidence_access' only under the owner's case-specific evidence-access consent; else supplied documents only."""
    try:
        from app.modules.consent.service import gate_allows

        return "evidence_access" if gate_allows(db, eng.company_id, "auditor_specialist_evidence_access", None, recipient=eng.id) else "supplied_documents_only"
    except ImportError:  # pragma: no cover
        return "supplied_documents_only"


# --- re-authentication ----------------------------------------------------------------------------------------


def reauth(db: Session, principal: Any) -> ReauthAssertion:
    a = ReauthAssertion(identity_uuid=principal.identity_uuid)
    db.add(a)
    db.flush()
    record_event(db, event_type="REAUTH_RECORDED", category="sign_in", actor_key=principal.actor_key, details={"method": a.method})
    return a


def require_reauth(db: Session, principal: Any, ref: str | None, *, now: datetime | None = None) -> ReauthAssertion:
    now = now or utcnow()
    max_age = timedelta(minutes=int(_cfg(db, "auditagent.reauth.max_age_minutes", 5)))
    a = db.get(ReauthAssertion, ref) if ref else None
    if a is None or a.identity_uuid != principal.identity_uuid or now - a.at > max_age:
        record_event(db, event_type="REAUTH_FAILED", category="sign_in", outcome="refused", reason_code="REAUTH_REQUIRED", actor_key=principal.actor_key)
        raise Forbidden("Confirm it is you with UAE PASS again (within 5 minutes) to record this act.", reason_code="REAUTH_REQUIRED", details={"max_age_minutes": max_age.seconds // 60})
    return a


# --- review acts ---------------------------------------------------------------------------------------------


def open_exceptions(db: Session, company_id: str) -> list[ExceptionFlag]:
    return list(db.scalars(select(ExceptionFlag).where(ExceptionFlag.company_id == company_id, ExceptionFlag.status == "New").order_by(ExceptionFlag.flagged_at)))


def _file(db: Session, eng: Engagement) -> AuditWorkingFile:
    f = db.get(AuditWorkingFile, eng.working_file_id) if eng.working_file_id else wf.current_file(db, eng.company_id)
    if f is None or not f.is_current:
        f = wf.current_file(db, eng.company_id)
    if f is None:
        raise Conflict("no audit work draft exists yet", reason_code="NO_DRAFT")
    return f


def review_action(db: Session, principal: Any, eng: Engagement, *, action: str, reauth_ref: str | None = None, reason_code: str | None = None, free_text: str | None = None, release_free_text: bool = False, reason_language: str = "en", now: datetime | None = None) -> dict:
    now = now or utcnow()
    f = _file(db, eng)
    who, role = principal.display_name, "licensed_auditor"
    if eng.auditor_identity_uuid != principal.identity_uuid:
        raise Forbidden("This engagement is not assigned to you.", reason_code="NOT_ASSIGNED")
    if action == "start_review":
        if f.completeness_state == "incomplete":
            raise Conflict("the draft is incomplete; sign-off status is 'not ready'", reason_code="NOT_READY")
        wf.transition(db, f, "under_review", who=who, role=role, actor_key=principal.actor_key)
        f.out_of_date = False
        eng.status = "under_review"
    elif action in ("record_review", "sign"):
        if action == "sign" and not get_config(db, "audit.signing.enabled", False):
            record_event(db, event_type="SIGN_BLOCKED", category="sign_off", outcome="refused", reason_code="SIGNING_SWITCHED_OFF", actor_key=principal.actor_key, actor_role=role, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id)
            raise SwitchedOff("Sign-off: not available in this version. Use 'Record review'.", reason_code="FEATURE_SWITCHED_OFF")
        a = require_reauth(db, principal, reauth_ref, now=now)
        open_n = len(open_exceptions(db, eng.company_id))
        if open_n:
            raise Conflict(f"Resolve all open exceptions first ({open_n} open).", reason_code="EXCEPTIONS_OPEN", details={"open": open_n, "text": both("resolve_open_first", n=open_n)})
        fw = _firewall(db, eng)
        from app.modules.delegates.service import firewall_clear

        if fw is None or not firewall_clear(db, eng.id, eng.auditor_identity_uuid):
            raise Forbidden("Signing blocked: licence not confirmed or engagement not assigned", reason_code="FIREWALL_NOT_CLEAR")
        rc = check_register(db, principal.identity_uuid, engagement_id=eng.id, purpose="sign" if action == "sign" else "review", now=now)
        if rc.outcome != "allowed":
            raise Forbidden("Your licence could not be checked. Review cannot be recorded until it is.", reason_code=rc.outcome.upper(), details={"register_check": register_check_dict(rc)})
        if f.status != "under_review":
            raise Conflict("start the review first", reason_code="NOT_UNDER_REVIEW")
        a.used_for = action
        supplied_only = evidence_mode(db, eng) == "supplied_documents_only"
        if action == "record_review":
            rr = AuditorReviewRecord(engagement_id=eng.id, file_id=f.id, file_version_no=f.version_no, version_hash=f.content_hash, reviewer_identity_uuid=principal.identity_uuid, reviewer_name=who, register_no=eng.register_ref, reauth_ref=a.id, snapshot_id=rc.snapshot_id, supplied_documents_only=supplied_only)
            db.add(rr)
            f.human_approved_content = {"reviewed_version_hash": f.content_hash, "decisions": "see exception decisions", "label": "internal record, not a signature"}
            f.reviewer_name = who
            eng.status = "review_recorded"
            record_event(db, event_type="REVIEW_RECORDED", category="sign_off", actor_key=principal.actor_key, actor_role=role, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"version_hash": f.content_hash, "reauth_ref": a.id, "snapshot_id": rc.snapshot_id, "supplied_documents_only": supplied_only})
        else:
            db.add(SignRecord(engagement_id=eng.id, file_id=f.id, signer_identity_uuid=principal.identity_uuid, licence_number=eng.register_ref, firm=eng.firm_name, version_hash=f.content_hash, register_snapshot_id=rc.snapshot_id, reauth_ref=a.id))
            wf.transition(db, f, "signed", who=who, role=role, actor_key=principal.actor_key, via_signing=True)
            f.signer_name, f.licence_number, f.signed_at, f.document_hash = who, eng.register_ref, now, f.content_hash
            record_event(db, event_type="AUDIT_REPORT_SIGNED", category="sign_off", actor_key=principal.actor_key, actor_role=role, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id)
    elif action in ("request_changes", "reject"):
        require_reauth(db, principal, reauth_ref, now=now)
        if reason_code not in REJECTION_CODES:
            raise ValidationFailed("choose a coded reason", reason_code="REASON_CODE_REQUIRED", details={"codes": list(REJECTION_CODES)})
        min_chars = int(_cfg(db, "auditagent.return_reason.min_chars", 10))
        if free_text and len(free_text.strip()) < min_chars:
            raise ValidationFailed(f"the reason must have at least {min_chars} characters", reason_code="REASON_TOO_SHORT")
        if f.status != "under_review":
            raise Conflict("only a draft under review can be returned", reason_code="NOT_UNDER_REVIEW")
        db.add(ReturnRecord(engagement_id=eng.id, file_id=f.id, kind=action, reason_code=reason_code, free_text=(free_text or None), release_free_text=release_free_text, reason_language=reason_language, by_uuid=principal.identity_uuid, by_name=who))
        wf.transition(db, f, "rejected", who=who, role=role, actor_key=principal.actor_key)
        if action == "request_changes":
            wf.transition(db, f, "draft", who="Qeonix audit operations", role="qeonix_audit_ops", actor_key=principal.actor_key)
            eng.status = "returned_to_preparation"
        else:
            eng.status = "rejected"
        record_event(db, event_type="RETURN_TO_PREPARATION" if action == "request_changes" else "AUDIT_DRAFT_RETURNED", category="sign_off", actor_key=principal.actor_key, actor_role=role, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"reason_code": reason_code, "free_text_released": release_free_text})
    else:
        raise ValidationFailed("unknown review action", reason_code="ACTION_INVALID")
    eng.last_activity_at = now
    db.flush()
    return engagement_dict(db, eng, viewer="auditor")


def record_signed_outside(db: Session, principal: Any, eng: Engagement, *, signer_name: str, register_number: str, date_signed: date, document_reference: str, confirmed: bool, reporter_role: str = "licensed_auditor") -> SignedOutsideRecord:
    """Created only by the auditor (or an administrator acting for them); every edit versioned; never automated."""
    if not confirmed:
        raise ValidationFailed("tick 'I confirm this was signed outside the platform'", reason_code="CONFIRMATION_REQUIRED")
    f = _file(db, eng)
    prev = db.scalar(select(SignedOutsideRecord).where(SignedOutsideRecord.engagement_id == eng.id, SignedOutsideRecord.is_current.is_(True)))
    version = 1
    if prev is not None:
        prev.is_current = False
        version = prev.version + 1
    rec = SignedOutsideRecord(engagement_id=eng.id, version=version, reporter_name=principal.display_name, reporter_role=reporter_role, signer_name=signer_name, register_number=register_number, date_signed=date_signed, document_reference=document_reference, file_version_no=f.version_no, confirmed=True)
    db.add(rec)
    eng.status, eng.last_activity_at = "signed_outside_platform", utcnow()
    db.flush()
    record_event(db, event_type="SIGNED_OUTSIDE_PLATFORM_RECORDED", category="sign_off", actor_key=principal.actor_key, actor_role=reporter_role, company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"version": version, "file_version_no": f.version_no})
    return rec


# --- reminders and escalations -----------------------------------------------------------------------------------


def run_engagement_reminders(db: Session, *, today: date | None = None, now: datetime | None = None) -> dict:
    """In-portal reminders at 14, 7 and 2 days before the deadline plus a due-date notice (no financial figures);
    escalation to the engagement manager after 3 working days without activity; 7 days before and not under review
    -> preparing team + engagement manager; 2 days unsigned -> DET pilot manager; lapsed -> both, owner told."""
    today = today or dubai_today()
    now = now or utcnow()
    offsets = list(_cfg(db, "auditagent.reminders.before_deadline_days", [14, 7, 2]))
    untouched = float(_cfg(db, "auditagent.escalation.untouched_working_days", 3))
    sent = esc = 0
    try:
        from app.modules.escalation.calendar import working_days_between
    except ImportError:  # pragma: no cover
        def working_days_between(_db, a, b):  # type: ignore
            return float((b - a).days)
    for eng in db.scalars(select(Engagement).where(Engagement.status.in_(("awaiting_review", "under_review", "returned_to_preparation")))):
        rem = list(eng.reminders_sent or [])
        escs = list(eng.escalations_sent or [])
        if eng.review_deadline:
            left = (eng.review_deadline - today).days
            for off in offsets:
                key = f"d-{off}"
                if left <= off and key not in rem and left >= 0:
                    rem.append(key)
                    sent += 1
                    record_event(db, event_type="REMINDER_SENT", category="reminder", company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"days_before": off, "deadline": eng.review_deadline.isoformat(), "status": eng.status})
            if left == 0 and "due" not in rem:
                rem.append("due")
                sent += 1
                record_event(db, event_type="REMINDER_SENT", category="reminder", company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"due_date_notice": True})
            for key, cond, to in (("not_under_review_7", left <= 7 and eng.status != "under_review", ["preparing_team", "engagement_manager"]), ("unsigned_2", left <= 2, ["det_pilot_manager"]), ("lapsed", left < 0, ["engagement_manager", "det_pilot_manager", "owner"])):
                if cond and key not in escs:
                    escs.append(key)
                    esc += 1
                    record_event(db, event_type="ESCALATION_SENT", category="reminder", company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"rule": key, "to": to})
        idle = working_days_between(db, eng.last_activity_at, now)
        key = f"idle-{eng.last_activity_at.date().isoformat()}"
        if idle >= untouched and key not in escs:
            escs.append(key)
            esc += 1
            record_event(db, event_type="ESCALATION_SENT", category="reminder", company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"rule": "untouched_working_days", "working_days": idle, "to": ["engagement_manager"]})
        eng.reminders_sent, eng.escalations_sent = rem, escs
    db.flush()
    return {"reminders": sent, "escalations": esc}


# --- serialisation -----------------------------------------------------------------------------------------------


def engagement_dict(db: Session, eng: Engagement, *, viewer: str = "auditor") -> dict:
    from app.modules.companies.models import Company

    co = db.get(Company, eng.company_id)
    f = None
    try:
        f = _file(db, eng)
    except Conflict:
        f = None
    rc = db.get(RegisterCheck, eng.register_check_id) if eng.register_check_id else None
    fw = firewall_record(db, eng)
    open_n = len(open_exceptions(db, eng.company_id))
    review = db.scalar(select(AuditorReviewRecord).where(AuditorReviewRecord.engagement_id == eng.id, AuditorReviewRecord.void.is_(False)).order_by(AuditorReviewRecord.recorded_at.desc()).limit(1))
    outside = db.scalar(select(SignedOutsideRecord).where(SignedOutsideRecord.engagement_id == eng.id, SignedOutsideRecord.is_current.is_(True)))
    mode = evidence_mode(db, eng)
    try:
        from app.modules.delegates.service import firewall_row

        fw_row = firewall_row(fw) if fw else None
    except ImportError:  # pragma: no cover
        fw_row = None
    return {
        "id": eng.id, "company_id": eng.company_id, "company": {"en": co.trade_name_en, "ar": co.trade_name_ar} if co else None, "status": eng.status,
        "auditor_name": eng.auditor_name, "register_ref": eng.register_ref, "firm_name": eng.firm_name, "engagement_manager": eng.engagement_manager, "engagement_manager_is_fallback": eng.engagement_manager_is_fallback,
        "preparing_team": "Qeonix audit operations", "assigned_at": eng.assigned_at.isoformat(), "review_deadline": eng.review_deadline.isoformat() if eng.review_deadline else None,
        "working_file": wf.file_dict(db, f, role="licensed_auditor") if f else None, "open_exceptions": open_n, "open_exceptions_text": both("resolve_open_first", n=open_n) if open_n else None,
        "register_check": register_check_dict(rc), "firewall": fw_row, "independence_declared": bool(fw and fw.independence_declared_at),
        "evidence_mode": mode, "supplied_documents_text": both("supplied_documents_only") if mode == "supplied_documents_only" else None,
        "badge": both("sc13_badge"), "ai_notice": both("sc13_ai_notice"), "signing_enabled": bool(get_config(db, "audit.signing.enabled", False)), "primary_action": "record_review" if not get_config(db, "audit.signing.enabled", False) else "sign",
        "sign_off_label": {"en": "Sign-off: not available in this version / Signed outside platform", "ar": "التوقيع: غير متاح في هذه النسخة / موقّع خارج المنصة"},
        "review_recorded": None if review is None else both("review_recorded", name=review.reviewer_name, x=review.register_no or "", date=review.recorded_at.date().isoformat()),
        "signed_outside": None if outside is None else {"version": outside.version, "signer_name": outside.signer_name, "register_number": outside.register_number, "date_signed": outside.date_signed.isoformat(), "document_reference": outside.document_reference, "text": both("signed_outside", name=outside.reporter_name, role=outside.reporter_role, date=outside.date_signed.isoformat())},
        "reminders_sent": eng.reminders_sent, "escalations_sent": eng.escalations_sent, "is_demo": eng.is_demo,
        "rejection_codes": list(REJECTION_CODES),
    }
