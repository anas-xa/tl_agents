"""Escalation endpoints: owner cases and Q&A, specialist/ops queue and actions, DET K21/K22 tiles, calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound, PlatformError
from app.core.time import dubai_today
from app.modules.access.service import Principal, authorize
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.escalation import service as svc
from app.modules.escalation.calendar import calendar_versions, holidays_between, working_days_between
from app.modules.escalation.metrics import compute_aggregates
from app.modules.escalation.models import OpsAlert, SpecialistEntitlement
from app.modules.escalation.strings import bilingual

company_router = APIRouter(prefix="/api/companies/{company_id}", tags=["escalation"])
cases_router = APIRouter(prefix="/api/cases", tags=["cases"])
det_router = APIRouter(prefix="/api/det", tags=["det"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
routers = [company_router, cases_router, det_router, admin_router]


# --- owner side ------------------------------------------------------------------------------------


def _run(db: Session, fn):
    """Run a service call and commit; a refusal is committed too so the audit event of the refusal is kept."""
    try:
        out = fn()
    except PlatformError:
        db.commit()
        raise
    db.commit()
    return out



class OpenCaseIn(BaseModel):
    module: str = "tax"
    title: str | None = Field(default=None, max_length=255)
    linked_item_id: str | None = None
    topic_code: str | None = None
    due_date: date | None = None


@company_router.get("/cases")
def list_cases(company_id: str, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    cases = svc.list_company_cases(db, company_id)
    record_event(db, event_type="CASES_LISTED", category="data_access", actor_key=principal.actor_key, actor_role=svc._actor_role(principal, company_id), company_id=company_id, details={"count": len(cases)})
    out = {"information_label": bilingual("information_not_advice"), "no_route_message": bilingual("licensed_professional_can_review"), "can_reject": svc._is_owner_level(principal, company_id), "reject_disabled_reason": None if svc._is_owner_level(principal, company_id) else bilingual("only_owner_can_reject"), "reject_codes": {c: bilingual(f"reject.{c}") for c in ("R1", "R2", "R3", "R4", "R5")}, "cases": [svc.owner_view(db, c, principal.language) for c in cases], "shared_before_consent": ["case reference", "case type", "coded reason", "deadline", "priority", "company reference", "your own title"], "never_shared_before_consent": ["amounts", "counterparties", "transactions", "bank data", "tax calculations", "free text from company data"]}
    db.commit()
    return out


@company_router.post("/cases", status_code=201)
def open_user_case(company_id: str, body: OpenCaseIn, principal: Principal = Depends(require("escalation.open")), db: Session = Depends(get_db)):
    try:
        case = svc.open_user_case(db, principal, company_id, module=body.module, title=body.title, linked_item_id=body.linked_item_id, topic_code=body.topic_code, due_date=body.due_date)
    except svc.CaseSetupPending:
        db.commit()
        return {"status": "setting_up", "message": bilingual("case_setup_pending"), "case_id": None}
    out = svc.owner_view(db, case, principal.language)
    db.commit()
    return out


@company_router.get("/cases/{case_id}")
def get_case(company_id: str, case_id: str, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    case = svc.get_case(db, case_id)
    if case.company_id != company_id:
        raise NotFound("case not found", reason_code="CASE_NOT_FOUND")
    record_event(db, event_type="CASE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=svc._actor_role(principal, company_id), company_id=company_id, subject_type="escalation_case", subject_id=case_id)
    out = svc.owner_view(db, case, principal.language)
    out["access_log"] = svc.access_log(db, case)
    db.commit()
    return out


class RejectIn(BaseModel):
    reason_code: str
    note: str | None = Field(default=None, max_length=300)


@company_router.post("/cases/{case_id}/reject")
def reject(company_id: str, case_id: str, body: RejectIn, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    case = _company_case(db, company_id, case_id)
    _run(db, lambda: svc.reject_case(db, principal, case, reason_code=body.reason_code, note=body.note))
    out = svc.owner_view(db, case, principal.language)
    out["message"] = bilingual("case_rejected")
    db.commit()
    return out


@company_router.post("/cases/{case_id}/reopen")
def reopen(company_id: str, case_id: str, principal: Principal = Depends(require("escalation.open")), db: Session = Depends(get_db)):
    case = _company_case(db, company_id, case_id)
    new = svc.reopen_case(db, principal, case)
    out = svc.owner_view(db, new, principal.language)
    db.commit()
    return out


class AnswerIn(BaseModel):
    answer_ref: str | None = Field(default=None, max_length=80)
    document_refs: list[str] = Field(default_factory=list)


@company_router.post("/cases/{case_id}/answer")
def answer(company_id: str, case_id: str, body: AnswerIn, principal: Principal = Depends(require("escalation.open")), db: Session = Depends(get_db)):
    case = _company_case(db, company_id, case_id)
    svc.submit_owner_answer(db, principal, case, answer_ref=body.answer_ref, document_refs=body.document_refs)
    out = svc.owner_view(db, case, principal.language)
    db.commit()
    return out


class ConsentIn(BaseModel):
    decision: str  # grant | refuse
    scope: list[dict] = Field(default_factory=list)
    purpose: str = "case review"
    expiry_days: int | None = None


@company_router.post("/cases/{case_id}/consent")
def consent(company_id: str, case_id: str, body: ConsentIn, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    case = _company_case(db, company_id, case_id)
    if body.decision == "grant":
        scope = body.scope or (case.details or {}).get("requested_scope", [])
        grant = _run(db, lambda: svc.grant_case_access(db, principal, case, scope=scope, purpose=body.purpose, expiry_days=body.expiry_days))
        out = {"grant_id": grant.id, "expires_at": grant.expires_at.isoformat(), "case": svc.owner_view(db, case, principal.language)}
    elif body.decision == "refuse":
        svc.refuse_case_consent(db, principal, case)
        out = {"case": svc.owner_view(db, case, principal.language), "note": bilingual("supplied_documents_label", date=dubai_today().isoformat())}
    else:
        from app.core.errors import ValidationFailed

        raise ValidationFailed("decision must be grant or refuse", reason_code="DECISION_INVALID")
    db.commit()
    return out


@company_router.post("/cases/{case_id}/consent/revoke")
def revoke(company_id: str, case_id: str, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    case = _company_case(db, company_id, case_id)
    n = svc.revoke_case_access(db, principal, case)
    out = {"revoked": n, "case": svc.owner_view(db, case, principal.language)}
    db.commit()
    return out


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    urgent: bool = False
    language: str | None = None


@company_router.post("/ask")
def ask(company_id: str, body: AskIn, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    out = svc.ask_question(db, principal, company_id, question=body.question, urgent=body.urgent, lang=body.language)
    db.commit()
    return out


@company_router.post("/ask/{question_id}/retry")
def ask_retry(company_id: str, question_id: str, principal: Principal = Depends(require("escalation.view")), db: Session = Depends(get_db)):
    done = svc.retry_pending_escalations(db, principal, company_id, question_id=question_id)
    db.commit()
    return {"created": done}


def _company_case(db: Session, company_id: str, case_id: str):
    case = svc.get_case(db, case_id)
    if case.company_id != company_id:
        raise NotFound("case not found", reason_code="CASE_NOT_FOUND")
    return case


# --- specialist / escalation operations ---------------------------------------------------------------


@cases_router.get("/queue")
def queue(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = svc.queue_for(db, principal)
    out["ai_label"] = bilingual("ai_label")
    out["tax_path_enabled"] = bool(get_config(db, "escalation.tax_specialist_path.enabled", False))
    out["lawyer_path_enabled"] = bool(get_config(db, "escalation.lawyer_path.enabled", False))
    db.commit()
    return out


@cases_router.get("/{case_id}")
def specialist_case(case_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = svc.get_case(db, case_id)
    have = _run(db, lambda: svc._assert_staff(db, principal, "cases.view_assigned", "cases.assign", "cases.queue_fallback", "cases.view_metadata"))
    if case.assigned_to == principal.identity_uuid or (case.assigned_to is None and svc.specialist_type_for(principal) == case.specialist_type):
        out = svc.pre_consent_summary(db, principal, case)
        out["metadata"] = svc.case_metadata(db, case)
        out["access_log"] = svc.access_log(db, case)
        out["consent_wait"] = _consent_wait(db, case)
        out["mode"] = "specialist"
    elif have & {"cases.assign", "cases.queue_fallback", "cases.view_metadata"}:
        record_event(db, event_type="CASE_METADATA_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id)
        out = {"mode": "ops", "metadata": svc.case_metadata(db, case), "consent_wait": _consent_wait(db, case), "candidates": _candidates(db, case)}
    else:
        record_event(db, event_type="CASE_ACCESS_REFUSED", category="access", outcome="refused", reason_code="NOT_ASSIGNED", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id)
        db.commit()
        raise Forbidden("You no longer have access to this case.", reason_code="NOT_ASSIGNED")
    db.commit()
    return out


def _consent_wait(db: Session, case) -> dict | None:
    if not case.consent_requested_at:
        return None
    day = (datetime.utcnow() - case.consent_requested_at).days
    return {"day": day, "reminder_days": get_config(db, "consent_wait.reminder_days", [3, 7]), "ops_alert_day": get_config(db, "consent_wait.ops_alert_day", 7), "close_day": get_config(db, "consent_wait.close_day", 14), "reopen_window": get_config(db, "consent_wait.reopen_window", 30), "requested_at": case.consent_requested_at.isoformat(), "decision": case.consent_decision}


def _candidates(db: Session, case) -> list[dict]:
    rows = db.scalars(select(SpecialistEntitlement).where(SpecialistEntitlement.specialist_type == case.specialist_type, SpecialistEntitlement.is_current.is_(True)))
    return [{"identity_uuid": r.identity_uuid, "status": r.status, "valid_to": r.valid_to.isoformat() if r.valid_to else None, "register": r.register_used, "firm_agreement_signed": r.firm_agreement_signed} for r in rows]


class AssignIn(BaseModel):
    assignee_uuid: str


@cases_router.post("/{case_id}/assign")
def assign(case_id: str, body: AssignIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.assign_case(db, principal, svc.get_case(db, case_id), assignee_uuid=body.assignee_uuid))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


class AcceptIn(BaseModel):
    requested_scope: list[dict] = Field(default_factory=list)
    purpose: str | None = None


@cases_router.post("/{case_id}/accept")
def accept(case_id: str, body: AcceptIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.accept_case(db, principal, svc.get_case(db, case_id), requested_scope=body.requested_scope, purpose=body.purpose))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


class NoteRefIn(BaseModel):
    note_ref: str | None = None


@cases_router.post("/{case_id}/first-response")
def first_response(case_id: str, body: NoteRefIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.first_response(db, principal, svc.get_case(db, case_id), note_ref=body.note_ref))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


class RequestInfoIn(BaseModel):
    request_code: str = Field(min_length=1, max_length=40)


@cases_router.post("/{case_id}/request-info")
def request_info(case_id: str, body: RequestInfoIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.request_information(db, principal, svc.get_case(db, case_id), request_code=body.request_code))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


class ResolveIn(BaseModel):
    outcome: str
    limitation: bool = False
    supplied_documents_date: date | None = None


@cases_router.post("/{case_id}/resolve")
def resolve(case_id: str, body: ResolveIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    res = _run(db, lambda: svc.resolve_case(db, principal, svc.get_case(db, case_id), outcome=body.outcome, limitation=body.limitation, supplied_documents_date=body.supplied_documents_date))
    out = {"case": svc.case_metadata(db, res["case"]), "output_label": res["output_label"], "ai_label": res["ai_label"]}
    db.commit()
    return out


class CloseIn(BaseModel):
    reason_code: str


@cases_router.post("/{case_id}/close")
def close(case_id: str, body: CloseIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.close_case(db, principal, svc.get_case(db, case_id), reason_code=body.reason_code))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


class KeyIn(BaseModel):
    matter_key: str = Field(min_length=1, max_length=255)


@cases_router.post("/{case_id}/complete-key")
def complete_key(case_id: str, body: KeyIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _run(db, lambda: svc.complete_matter_key(db, principal, svc.get_case(db, case_id), matter_key=body.matter_key))
    out = svc.case_metadata(db, case)
    db.commit()
    return out


@cases_router.get("/{case_id}/items/{item}")
def read_item(case_id: str, item: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _run(db, lambda: svc.access_case_item(db, principal, svc.get_case(db, case_id), item=item))


@cases_router.post("/{case_id}/consent-wait/run")
def consent_wait_run(case_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    svc._assert_staff(db, principal, "cases.assign", "cases.queue_fallback", "cases.queue_alerts")
    svc.get_case(db, case_id)
    out = svc.run_consent_wait(db, case_id=case_id)
    svc.escalate_stale_alerts(db)
    db.commit()
    return out


@cases_router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    svc._assert_staff(db, principal, "cases.queue_alerts", "cases.queue_fallback")
    alert = db.get(OpsAlert, alert_id)
    if alert is None:
        raise NotFound("alert not found", reason_code="ALERT_NOT_FOUND")
    alert.acknowledged_at = datetime.utcnow()
    record_event(db, event_type="OPS_ALERT_ACKNOWLEDGED", category="escalation", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="ops_alert", subject_id=alert_id)
    db.commit()
    return {"id": alert_id, "acknowledged": True}


# --- DET dashboard: K21/K22 -------------------------------------------------------------------------------


@det_router.get("/escalations")
def escalations_dashboard(request: Request, period_from: date | None = None, period_to: date | None = None, module: str | None = None, reason: str | None = None, specialist_type: str | None = None, priority: str | None = None, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    try:
        authorize(db, principal, "escalation_dashboard.view", company_id=None)
    except Forbidden:
        record_event(db, event_type="DASHBOARD_NOACCESS_ATTEMPT", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"view": "escalations"})
        db.commit()
        raise Forbidden("This view is for DET administrators. Your own escalated cases are under Help.", reason_code="NO_PERMISSION") from None
    today = dubai_today()
    period_to = period_to or today
    period_from = period_from or (period_to - timedelta(days=89))
    out = compute_aggregates(db, period_from=period_from, period_to=period_to, module=module, reason=reason, specialist_type=specialist_type, priority=priority)
    out["titles"] = {"k21": bilingual("k21.title"), "k22": bilingual("k22.title"), "fewer_than_n": bilingual("k.fewer_than_n", n=out["suppression"]["min_group_size"]), "open_not_counted": bilingual("k.open_not_counted"), "aggregate_only": bilingual("k.aggregate_only")}
    out["viewer_role"] = "compliance_reviewer" if principal.has_staff("compliance_reviewer") else "det_admin"
    record_event(db, event_type="DASHBOARD_VIEW", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"view": "escalations", "filters": out["filters"], "period": out["period"]})
    db.commit()
    return out


# --- calendar -----------------------------------------------------------------------------------------------


@admin_router.get("/calendar")
def calendar(year: int | None = None, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    versions = calendar_versions(db)
    years = [year] if year else [v.effective_year for v in versions]
    out = {"calendar_id": "uae_working_calendar", "weekend": ["saturday", "sunday"], "convention": get_config(db, "working_day.convention", {}), "versions": [{"effective_year": v.effective_year, "version": v.version, "source_ref": v.source_ref, "version_date": v.version_date.isoformat(), "updated_by": v.updated_by} for v in versions], "holidays": []}
    for y in years:
        for d, h in sorted(holidays_between(db, date(y, 1, 1), date(y, 12, 31)).items()):
            out["holidays"].append({"date": d.isoformat(), "name_en": h.name_en, "name_ar": h.name_ar, "status": h.status, "year": y, "version": h.version})
    db.commit()
    return out


@admin_router.get("/calendar/working-days")
def calendar_working_days(start: date, end: date, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return {"start": start.isoformat(), "end": end.isoformat(), "working_days": working_days_between(db, start, end)}

