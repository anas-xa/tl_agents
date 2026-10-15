"""Audit agent API: SC8 (owner audit preparation status), SC13 (auditor review workspace), DET K20 aggregates."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound, PlatformError, ValidationFailed
from app.modules.access.service import Principal, authorize, permissions_for, require_company_access
from app.modules.audit.service import record_event
from app.modules.auditagent import engagement as eng_svc
from app.modules.auditagent import indicator as ind
from app.modules.auditagent import review as rv
from app.modules.auditagent import workfile as wf
from app.modules.auditagent.models import AuditCriteriaVersion, ExceptionFlag
from app.modules.auditagent.strings import both

router = APIRouter(tags=["audit agent"])

def logged_db(db: Session = Depends(get_db)):
    """Same request session; refusals are logged before the error is returned (fail-closed audit entries persist)."""
    try:
        yield db
    except PlatformError:
        db.commit()
        raise



def _role(principal: Principal, company_id: str) -> str:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else principal.primary_role()


def _has_audit_function(principal: Principal, company_id: str) -> bool:
    for r in principal.roles_for(company_id):
        if r.role in ("owner", "remote_owner") or "audit" in (r.functions or []) or "all" in (r.functions or []):
            return True
    return False


def _empty_state(db: Session, company_id: str, flags: list, cycle) -> str | None:
    ledger = rv.source_gate(db, company_id, "ledger")
    if ledger.get("state") == "withdrawn":
        return "consent_withdrawn"
    if not ledger.get("allowed") and not rv.source_gate(db, company_id, "bank").get("allowed"):
        return "no_source" if not flags else None
    if not flags:
        return "no_exceptions" if cycle else "no_review_yet"
    return None


@router.get("/api/companies/{company_id}/audit")
def audit_overview(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    role = _role(principal, company_id)
    row = ind.latest_result(db, company_id)
    out: dict = {"role": role, "flag": ind.result_dict(db, row, log_display=True, actor_key=principal.actor_key, company_id=company_id), "flag_prompt": both("flag_prompt")}
    perms = permissions_for(db, principal, company_id)
    can_act = role == "owner" or (role == "delegate" and _has_audit_function(principal, company_id))
    out["can"] = {"acknowledge": can_act, "hide_banner": role == "owner", "dispute": "audit.request_review" in perms, "request_review": "audit.request_review" in perms or (role == "delegate" and _has_audit_function(principal, company_id)), "ask_auditor": False, "decide": role == "owner" or (role == "delegate" and _has_audit_function(principal, company_id)), "escalate": "escalation.open" in perms and role != "remote_owner", "download": role != "remote_owner", "edit_inputs": "taxprofile.edit" in perms, "run_review": role != "remote_owner"}
    if role == "remote_owner":
        out["exceptions"] = None
        out["exceptions_hidden_reason"] = {"en": "Flag details are available to owners in the UAE and their delegates.", "ar": "تفاصيل التنبيهات متاحة للمالكين داخل الإمارات ومفوّضيهم."}
        out["read_only_note"] = {"en": "Your role can view this. Ask the owner for access to change it.", "ar": "يمكن لدورك الاطلاع على هذا فقط. اطلب من المالك صلاحية التعديل."}
        out["download_note"] = both_download()
    else:
        flags = rv.list_flags(db, company_id, include_bank=rv.bank_rules_visible(db, company_id))
        cyc = rv.last_cycle(db, company_id)
        out["exceptions"] = [rv.flag_dict(db, f, detail=False) for f in flags]
        out["review"] = {"last_cycle_at": cyc.finished_at.isoformat() if cyc and cyc.finished_at else None, "status": cyc.status if cyc else None, "sources_read": cyc.sources_read if cyc else [], "sources_refused": cyc.sources_refused if cyc else {}, "more_available": bool(cyc and cyc.more_available), "empty_state": _empty_state(db, company_id, flags, cyc), "bank_rules_visible": rv.bank_rules_visible(db, company_id), "ended_on": rv.source_gate(db, company_id, "ledger").get("ended_on")}
        if role == "delegate" and not _has_audit_function(principal, company_id):
            out["decide_disabled_reason"] = {"en": "You can view this flag. Ask the owner to give you the right to decide.", "ar": "يمكنك عرض هذا التنبيه. اطلب من المالك منحك صلاحية اتخاذ القرار."}
    if role == "delegate" and not _has_audit_function(principal, company_id):
        out["working_file"] = None
        out["working_file_hidden"] = {"en": "You do not have access to audit status for this company. Ask the owner to assign it.", "ar": "ليس لديك صلاحية الاطلاع على حالة التدقيق لهذه الشركة. اطلب من المالك إسنادها إليك."}
    else:
        f = wf.current_file(db, company_id)
        out["working_file"] = wf.file_dict(db, f, role=role) if f else None
        if f is None:
            ps, pe, _ = rv.default_period(db, company_id)
            out["working_file_empty"] = both("no_draft_yet", date=pe.isoformat())
    db.commit()
    return out


def both_download() -> dict:
    return {"en": "Download is not available for your role in this version. You can view everything on this page. Ask DET or your delegate for a copy.", "ar": "التنزيل غير متاح لدورك في هذه النسخة. يمكنك عرض كل شيء في هذه الصفحة. اطلب نسخة من الإدارة أو من مفوّضك."}


class FlagActionIn(BaseModel):
    action: str
    reason_code: str | None = None
    reason: str | None = None


@router.post("/api/companies/{company_id}/audit/flag/actions")
def flag_action(company_id: str, body: FlagActionIn, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    role = _role(principal, company_id)
    if body.action in ("dispute", "request_review") and role != "delegate":
        authorize(db, principal, "audit.request_review", company_id=company_id)
    if role == "delegate" and not _has_audit_function(principal, company_id):
        raise Forbidden("Your role can view this. Ask the owner for access to change it.", reason_code="READ_ONLY_ROLE")
    out = ind.owner_action(db, principal, company_id, action=body.action, role=role, reason_code=body.reason_code, reason_text=body.reason)
    db.commit()
    return out


class InputsIn(BaseModel):
    tax_group_member: str | None = None
    qfzp: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    revenue_fils: int | None = None
    vat_fils: int | None = None


@router.post("/api/companies/{company_id}/audit/inputs")
def set_inputs(company_id: str, body: InputsIn, principal: Principal = Depends(require("taxprofile.edit")), db: Session = Depends(logged_db)):
    ind.set_inputs(db, company_id, actor_name=principal.display_name, actor_role=_role(principal, company_id), actor_key=principal.actor_key, payload=body.model_dump())
    out = ind.result_dict(db, ind.latest_result(db, company_id))
    db.commit()
    return out


@router.post("/api/companies/{company_id}/audit/flag/recompute")
def recompute(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    ind.request_recompute(db, company_id, "manual_retry")
    out = ind.result_dict(db, ind.latest_result(db, company_id))
    db.commit()
    return out


@router.post("/api/companies/{company_id}/audit/review/run")
def run_review(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    if _role(principal, company_id) == "remote_owner":
        raise Forbidden("Your role can view this. Ask the owner for access to change it.", reason_code="READ_ONLY_ROLE")
    cyc = rv.run_review_cycle(db, company_id, actor_key=principal.actor_key)
    db.commit()
    return {"cycle_id": cyc.id, "status": cyc.status, "sources_read": cyc.sources_read, "sources_refused": cyc.sources_refused, "flags_created": cyc.flags_created, "revisions_created": cyc.revisions_created, "more_available": cyc.more_available, "rule_versions": cyc.rule_versions, "model_version": cyc.model_version}


@router.get("/api/companies/{company_id}/audit/exceptions/{flag_id}")
def exception_detail(company_id: str, flag_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    if _role(principal, company_id) == "remote_owner":
        raise Forbidden("Flag details are available to owners in the UAE and their delegates.", reason_code="REMOTE_OWNER_SUMMARY_ONLY")
    out = rv.flag_dict(db, rv.get_flag(db, company_id, flag_id))
    record_event(db, event_type="DATA_ACCESS", category="data_access", actor_key=principal.actor_key, company_id=company_id, subject_type="exception_flag", subject_id=flag_id)
    db.commit()
    return out


class DecideIn(BaseModel):
    decision: str
    reason: str = ""
    reason_code: str | None = None


def _decide(db: Session, principal: Principal, company_id: str, flag_id: str, body: DecideIn) -> dict:
    flag = rv.get_flag(db, company_id, flag_id)
    eng = None
    staff_prepare = False
    if principal.roles_for(company_id):
        require_company_access(db, principal, company_id)
        authorize(db, principal, "audit.view", company_id=company_id)
    else:
        if principal.has_staff("licensed_auditor"):
            eng = eng_svc.auditor_engagement_for_company(db, principal.identity_uuid, company_id)
            if eng is not None:
                from app.modules.delegates.service import firewall_clear

                if not firewall_clear(db, eng.id, principal.identity_uuid):
                    raise Forbidden("Signing blocked: licence not confirmed or engagement not assigned", reason_code="FIREWALL_NOT_CLEAR")
        staff_prepare = "audit.prepare" in permissions_for(db, principal, None)
        if eng is None and not staff_prepare:
            record_event(db, event_type="UNASSIGNED_ACCESS_DENIED", category="access", outcome="refused", reason_code="NOT_ASSIGNED", actor_key=principal.actor_key, company_id=company_id)
            raise Forbidden("This engagement is not assigned to you.", reason_code="NOT_ASSIGNED")
    role, label = rv.require_decide_right(principal, company_id, has_engagement=eng is not None, staff_prepare=staff_prepare)
    if body.decision == "escalate":
        if role == "delegate":
            authorize(db, principal, "escalation.open", company_id=company_id)
        rv.escalate_flag(db, flag, actor_key=principal.actor_key, actor_role=role)
    else:
        if role == "licensed_auditor" and body.decision == "explain":
            raise ValidationFailed("auditors confirm or dismiss", reason_code="DECISION_INVALID")
        rv.decide(db, flag, decision=body.decision, reason=body.reason, decided_by_uuid=principal.identity_uuid, decided_by_name=principal.display_name, actor_role=role, role_label=label, actor_key=principal.actor_key, engagement_id=eng.id if eng else None, reason_code=body.reason_code)
        if eng is not None:
            from app.core.time import utcnow

            eng.last_activity_at = utcnow()
    out = rv.flag_dict(db, flag)
    db.commit()
    return out


@router.post("/api/companies/{company_id}/audit/exceptions/{flag_id}/decide")
def decide(company_id: str, flag_id: str, body: DecideIn, principal: Principal = Depends(get_principal), db: Session = Depends(logged_db)):
    return _decide(db, principal, company_id, flag_id, body)


@router.post("/api/companies/{company_id}/audit/working-file/prepare")
def prepare(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    if not _has_audit_function(principal, company_id) or _role(principal, company_id) == "remote_owner":
        raise Forbidden("You do not have access to audit status for this company. Ask the owner to assign it.", reason_code="NO_AUDIT_FUNCTION")
    out = wf.prepare_working_file(db, company_id, actor_key=principal.actor_key)
    db.commit()
    return out


@router.get("/api/companies/{company_id}/audit/working-file/export", response_class=HTMLResponse)
def export(company_id: str, lang: str = "en", principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    role = _role(principal, company_id)
    if role == "remote_owner":
        raise Forbidden(both_download()["en"], reason_code="DOWNLOAD_NOT_AVAILABLE_FOR_ROLE", details={"text": both_download()})
    if not _has_audit_function(principal, company_id):
        raise Forbidden("You do not have access to audit status for this company. Ask the owner to assign it.", reason_code="NO_AUDIT_FUNCTION")
    f = wf.current_file(db, company_id)
    if f is None:
        raise NotFound("No audit work draft yet.", reason_code="NO_DRAFT")
    if f.out_of_date:
        raise Forbidden("Export is disabled until the revised draft is ready.", reason_code="OUT_OF_DATE")
    body = wf.render_export(db, f, lang=lang)
    record_event(db, event_type="EXPORT_GENERATED", category="document", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="audit_working_file", subject_id=f.id, details={"watermarked": True, "lang": lang, "version_no": f.version_no})
    db.commit()
    return HTMLResponse(body)


@router.post("/api/companies/{company_id}/audit/working-file/release")
def release(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    f = wf.current_file(db, company_id)
    if f is None:
        raise NotFound("No audit work draft yet.", reason_code="NO_DRAFT")
    try:
        wf.attempt_release(db, f, who=principal.display_name, role=_role(principal, company_id), actor_key=principal.actor_key)
    finally:
        db.commit()


class GapIn(BaseModel):
    action: str
    assignee_uuid: str | None = None
    assignee_name: str | None = None
    due_date: date | None = None
    reason: str | None = None


@router.post("/api/companies/{company_id}/audit/gaps/{gap_id}")
def gap(company_id: str, gap_id: str, body: GapIn, principal: Principal = Depends(require("audit.view")), db: Session = Depends(logged_db)):
    if not _has_audit_function(principal, company_id):
        raise Forbidden("You do not have access to audit status for this company. Ask the owner to assign it.", reason_code="NO_AUDIT_FUNCTION")
    g = wf.gap_action(db, wf.get_gap(db, company_id, gap_id), action=body.action, actor_name=principal.display_name, actor_role=_role(principal, company_id), actor_key=principal.actor_key, assignee_uuid=body.assignee_uuid, assignee_name=body.assignee_name, due_date=body.due_date, reason=body.reason)
    db.commit()
    return wf.gap_dict(g)


# --- SC13 auditor workspace ---------------------------------------------------------------------------------


@router.get("/api/auditor/engagements")
def queue(principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    rows = []
    for e in eng_svc.list_for(db, principal):
        from app.modules.companies.models import Company

        co = db.get(Company, e.company_id)
        f = wf.current_file(db, e.company_id)
        rows.append({"id": e.id, "company_id": e.company_id, "company": {"en": co.trade_name_en, "ar": co.trade_name_ar} if co else None, "status": e.status, "review_deadline": e.review_deadline.isoformat() if e.review_deadline else None, "open_exceptions": len(eng_svc.open_exceptions(db, e.company_id)), "completeness_state": f.completeness_state if f else None, "file_status": f.status if f else None, "is_demo": e.is_demo})
    db.commit()
    return {"engagements": rows, "empty": both_empty() if not rows else None}


def both_empty() -> dict:
    return {"en": "No engagements assigned to you. Assignments come from the audit service team.", "ar": "لا توجد مهام تدقيق مسندة إليك. تأتي الإسنادات من فريق خدمة التدقيق."}


def _masked_for_supplied_only(d: dict) -> dict:
    if d.get("source") in ("ledger", "bank") and d.get("evidence"):
        d["evidence"] = [{"record_id": r.get("record_id"), "record_version": r.get("record_version"), "source": r.get("source"), "date": r.get("date"), "masked": True} for r in d["evidence"]]
        d["evidence_note"] = both("supplied_documents_only")
    return d


@router.get("/api/auditor/engagements/{engagement_id}")
def engagement_detail(engagement_id: str, principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    eng_svc._firewall(db, eng)  # re-evaluated on each access; a new hit suspends the record
    out = eng_svc.engagement_dict(db, eng)
    flags = [rv.flag_dict(db, f) for f in rv.list_flags(db, eng.company_id)]
    if out["evidence_mode"] == "supplied_documents_only":
        flags = [_masked_for_supplied_only(f) for f in flags]
    out["exceptions"] = flags
    record_event(db, event_type="ENGAGEMENT_OPENED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=eng.company_id, subject_type="engagement", subject_id=eng.id, details={"evidence_mode": out["evidence_mode"]})
    db.commit()
    return out


class ReviewIn(BaseModel):
    action: str
    reauth_ref: str | None = None
    reason_code: str | None = None
    free_text: str | None = None
    release_free_text: bool = False
    reason_language: str = "en"


@router.post("/api/auditor/engagements/{engagement_id}/review")
def review(engagement_id: str, body: ReviewIn, principal: Principal = Depends(require_staff("audit.record_review")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    try:
        out = eng_svc.review_action(db, principal, eng, action=body.action, reauth_ref=body.reauth_ref, reason_code=body.reason_code, free_text=body.free_text, release_free_text=body.release_free_text, reason_language=body.reason_language)
    except Exception:
        db.commit()  # keep the refusal log entries
        raise
    db.commit()
    return out


@router.post("/api/auditor/engagements/{engagement_id}/exceptions/{flag_id}/decide")
def auditor_decide(engagement_id: str, flag_id: str, body: DecideIn, principal: Principal = Depends(require_staff("audit.review")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    return _decide(db, principal, eng.company_id, flag_id, body)


@router.post("/api/auditor/reauth")
def do_reauth(principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    a = eng_svc.reauth(db, principal)
    db.commit()
    return {"reauth_ref": a.id, "at": a.at.isoformat(), "max_age_minutes": 5}


@router.post("/api/auditor/engagements/{engagement_id}/independence")
def independence(engagement_id: str, principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    eng = eng_svc.get_engagement(db, engagement_id)
    eng_svc.declare_independence(db, principal, eng)
    db.commit()
    return eng_svc.engagement_dict(db, eng)


@router.post("/api/auditor/engagements/{engagement_id}/register-check")
def register_check(engagement_id: str, principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    rc = eng_svc.check_register(db, eng.auditor_identity_uuid, engagement_id=eng.id, purpose="review")
    eng.register_check_id = rc.id
    db.commit()
    return eng_svc.register_check_dict(rc)


class SignedOutsideIn(BaseModel):
    signer_name: str
    register_number: str
    date_signed: date
    document_reference: str
    confirmed: bool = False


@router.post("/api/auditor/engagements/{engagement_id}/signed-outside")
def signed_outside(engagement_id: str, body: SignedOutsideIn, principal: Principal = Depends(require_staff("audit.review")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    eng_svc.record_signed_outside(db, principal, eng, signer_name=body.signer_name, register_number=body.register_number, date_signed=body.date_signed, document_reference=body.document_reference, confirmed=body.confirmed)
    db.commit()
    return eng_svc.engagement_dict(db, eng)


@router.get("/api/auditor/engagements/{engagement_id}/export", response_class=HTMLResponse)
def auditor_export(engagement_id: str, lang: str = "en", principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(logged_db)):
    eng = eng_svc.require_assigned(db, principal, engagement_id)
    f = wf.current_file(db, eng.company_id)
    if f is None:
        raise NotFound("No audit work draft yet.", reason_code="NO_DRAFT")
    body = wf.render_export(db, f, lang=lang, supplied_documents_only=eng_svc.evidence_mode(db, eng) == "supplied_documents_only")
    record_event(db, event_type="EXPORT_GENERATED", category="document", actor_key=principal.actor_key, actor_role="licensed_auditor", company_id=eng.company_id, subject_type="audit_working_file", subject_id=f.id, details={"watermarked": True, "lang": lang})
    db.commit()
    return HTMLResponse(body)


class AssignIn(BaseModel):
    company_id: str
    auditor_identity_uuid: str
    firm_name: str | None = None
    engagement_manager: str | None = None
    review_deadline: date | None = None


@router.post("/api/auditor/engagements")
def assign(body: AssignIn, principal: Principal = Depends(require_staff("audit.assign")), db: Session = Depends(logged_db)):
    try:
        e = eng_svc.create_engagement(db, company_id=body.company_id, auditor_uuid=body.auditor_identity_uuid, assigned_by=principal.display_name, firm_name=body.firm_name, engagement_manager=body.engagement_manager, review_deadline=body.review_deadline, actor_key=principal.actor_key)
    except Exception:
        db.commit()
        raise
    db.commit()
    return {"id": e.id, "status": e.status, "next": "the auditor records the independence declaration; then activate"}


@router.post("/api/auditor/engagements/{engagement_id}/activate")
def activate(engagement_id: str, principal: Principal = Depends(require_staff("audit.assign")), db: Session = Depends(logged_db)):
    e = eng_svc.get_engagement(db, engagement_id)
    try:
        eng_svc.activate_engagement(db, e, actor_key=principal.actor_key)
    except Exception:
        db.commit()
        raise
    db.commit()
    return {"id": e.id, "status": e.status}


@router.post("/api/auditor/register/snapshots")
def load_snapshot(principal: Principal = Depends(require_staff("audit.register.load")), db: Session = Depends(logged_db)):
    snap = eng_svc.fetch_register_snapshot(db, loaded_by=principal.display_name)
    db.commit()
    return {"id": snap.id, "loaded_at": snap.loaded_at.isoformat(), "entries": len(snap.entries)}


# --- criteria governance --------------------------------------------------------------------------------------


@router.get("/api/audit-criteria")
def criteria(principal: Principal = Depends(get_principal), db: Session = Depends(logged_db)):
    if not principal.staff_roles:
        raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION")
    return [ind.criteria_dict(c) for c in db.scalars(select(AuditCriteriaVersion).order_by(AuditCriteriaVersion.effective_date))]


@router.post("/api/audit-criteria/{version_id}/confirm")
def criteria_confirm(version_id: str, principal: Principal = Depends(require_staff("audit.criteria.confirm")), db: Session = Depends(logged_db)):
    try:
        c = ind.confirm_criteria(db, version_id, confirmer=principal.display_name, confirmer_role="licensed_auditor")
    finally:
        db.commit()
    return ind.criteria_dict(c)


@router.post("/api/audit-criteria/{version_id}/publish")
def criteria_publish(version_id: str, principal: Principal = Depends(require_staff("audit.criteria.publish")), db: Session = Depends(logged_db)):
    c = ind.publish_criteria(db, version_id, publisher_role=principal.primary_role())
    db.commit()
    return ind.criteria_dict(c)


# --- DET aggregates ------------------------------------------------------------------------------------------


@router.get("/api/det/audit-flags")
def det_audit_flags(request: Request, principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(logged_db)):
    from app.modules.config.service import get_config

    minimum = int(get_config(db, "auditagent.k20.min_cell_size", 10) or 10)
    k16_rows = []
    for (rule_id, version), precision in rv.k16_by_rule_version(db).items():
        n = sum(r["confirmed"] + r["dismissed"] for r in rv.k16(db) if r["rule_id"] == rule_id and r["rule_version"] == version)
        k16_rows.append({"rule_id": rule_id, "rule_version": version, "decisions": n if n >= minimum else None, "precision": round(precision, 4) if (precision is not None and n >= minimum) else None, "suppressed": n < minimum})
    flags_total = db.scalar(select(ExceptionFlag.id).limit(1))
    k19 = wf.k19(db)
    k19["status_mix"] = {k: (v if v >= minimum else None) for k, v in k19["status_mix"].items()}
    k18 = wf.k18(db)
    if k18["n"] < minimum:
        k18 = {"n": None, "median_days": None, "mean_days": None, "incomplete_n": None, "suppressed": True}
    else:
        k18.pop("incomplete_open_age_days", None)
    out = {"k20": ind.k20(db), "k16": k16_rows, "k18": k18, "k19": k19, "has_flags": flags_total is not None, "note": {"en": "Aggregated counts only. No individual flags or evidence.", "ar": "أعداد مجمّعة فقط. لا تنبيهات فردية ولا أدلة."}}
    record_event(db, event_type="DET_AGGREGATES_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"view": "audit_flags"})
    db.commit()
    return out
