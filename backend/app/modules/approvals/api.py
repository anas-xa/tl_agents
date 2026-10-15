"""Approvals API (E6): approval requests and records, delegate approval grants (Phase B, switched off), the
manual filing path, the switched-off adapter path and the DET approval-compliance view (K23/K24)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, PlatformError
from app.modules.access.service import STAFF_PERMS, Principal, authorize, require_company_access
from app.modules.approvals import adapter, monitoring
from app.modules.approvals import service as svc
from app.modules.approvals.models import ApprovalRequest, DelegateApprovalGrant
from app.modules.approvals.strings import STRINGS
from app.modules.audit.service import record_event
from app.modules.drafts.models import DraftPack

router = APIRouter(prefix="/api/companies/{company_id}/approvals", tags=["approvals"])
grants_router = APIRouter(prefix="/api/companies/{company_id}/delegate-grants", tags=["approvals"])
det_router = APIRouter(prefix="/api/det/approval-compliance", tags=["approvals"])
ops_router = APIRouter(prefix="/api/approvals", tags=["approvals"])
routers = [router, grants_router, det_router, ops_router]


def _strings(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in STRINGS.items()}


def member(*permissions: str) -> Callable:
    """Company isolation; a person whose owner-level role is blocked (no matched Emirates ID) is refused with
    NO_OWNER_ROLE. Refusals are committed (logged) before the error is returned."""

    def _dep(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        cid = request.path_params["company_id"]
        try:
            if not principal.roles_for(cid) and svc.owner_blocked(db, principal, cid):
                record_event(db, event_type="APPROVAL_REFUSED", category="approval", outcome="refused", reason_code="NO_OWNER_ROLE", actor_key=principal.actor_key, company_id=cid)
                raise Forbidden(STRINGS["NO_OWNER_ROLE"]["en"], reason_code="NO_OWNER_ROLE")
            require_company_access(db, principal, cid)
            last: PlatformError | None = None
            for p in permissions:
                try:
                    authorize(db, principal, p, company_id=cid, log=False)
                    last = None
                    break
                except PlatformError as e:
                    last = e
            if last is not None:
                authorize(db, principal, permissions[0], company_id=cid)
        except PlatformError:
            db.commit()
            raise
        db.commit()
        return principal

    return _dep


def _run(db: Session, fn: Callable, *args, **kwargs):
    """Refusals are fail-safe: the refusal event is committed, then the action is refused."""
    try:
        out = fn(*args, **kwargs)
    except PlatformError:
        db.commit()
        raise
    db.commit()
    return out


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


# --- approvals -------------------------------------------------------------------------------------


@router.get("")
def list_approvals(company_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    reqs = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == company_id).order_by(ApprovalRequest.created_at.desc())))
    for r in reqs:
        svc.refresh_request(db, r)
    role = svc.role_on(principal, company_id)
    packs = []
    if role in ("owner", "delegate"):
        open_packs = {r.pack_id for r in reqs if r.status in ("open", "blocked", "decided")}
        for p in db.scalars(select(DraftPack).where(DraftPack.company_id == company_id, DraftPack.superseded.is_(False), DraftPack.locked.is_(False)).order_by(DraftPack.created_at.desc())):
            if p.id not in open_packs and not p.on_hold and p.review_status not in svc.UNAPPROVABLE and p.review_status != "approved_for_submission":
                packs.append({"pack_id": p.id, "tax_type": p.tax_type, "period_id": p.period_id, "version": p.version, "review_status": p.review_status, "not_reviewed_by_human": p.review_status in svc.NOT_REVIEWED, "is_demo": p.is_demo})
    record_event(db, event_type="APPROVALS_LISTED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"count": len(reqs)})
    out = {
        "role": role, "flow_enabled": svc.flow_enabled(db), "phase_b_on": svc.phase_b_on(db, company_id),
        "can_send": role in ("owner", "delegate"), "requests": [svc.request_dict(db, r, principal=principal) for r in reqs],
        "awaiting": [svc.request_dict(db, r, principal=principal) for r in reqs if r.status in ("open", "blocked")],
        "history": monitoring.history_rows(db, company_id), "packs_ready": packs, "strings": _strings(principal.language),
    }
    db.commit()
    return out


@router.get("/fixtures")
def fixtures(company_id: str, principal: Principal = Depends(member("returns.view"))):
    return {"tag": "Demo data", "states": svc.demo_fixtures(principal.language)}


@router.get("/requests/{request_id}")
def get_request(company_id: str, request_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    req = svc.get_request(db, company_id, request_id)
    svc.refresh_request(db, req)
    record_event(db, event_type="APPROVAL_REQUEST_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=svc.role_on(principal, company_id), company_id=company_id, subject_type="approval_request", subject_id=req.id)
    out = svc.request_dict(db, req, principal=principal, detail=True) | {"role": svc.role_on(principal, company_id), "flow_enabled": svc.flow_enabled(db), "phase_b_on": svc.phase_b_on(db, company_id), "fixtures": svc.demo_fixtures(principal.language), "strings": _strings(principal.language)}
    db.commit()
    return out


class RequestIn(BaseModel):
    pack_id: str
    submission_type: str = "return_pack"


@router.post("/requests")
def create_request(company_id: str, body: RequestIn, principal: Principal = Depends(member("returns.send_for_approval", "returns.approve")), db: Session = Depends(get_db)):
    req = _run(db, svc.request_approval, db, principal, company_id, body.pack_id, submission_type=body.submission_type)
    return svc.request_dict(db, req, principal=principal)


class ApproveIn(BaseModel):
    expected_hash: str | None = None
    reviewed_figures: bool = False
    informed_unreviewed: bool = False
    uaepass: str | None = "confirmed"  # mock UAE PASS re-sign-in outcome: confirmed | failed | cancelled


@router.post("/{request_id}/approve")
def approve(company_id: str, request_id: str, body: ApproveIn, request: Request, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    """Entitlement (owner-level + authority evidence, or delegate grant with Phase B ON) and UAE PASS step-up are
    checked server-side at the moment of decision."""
    return _run(db, svc.approve, db, principal, company_id, request_id, expected_hash=body.expected_hash, reviewed_figures=body.reviewed_figures, informed_unreviewed=body.informed_unreviewed, uaepass=body.uaepass, user_agent=_ua(request))


class DeclineIn(BaseModel):
    decision: str = "request_changes"
    reason: str | None = None
    expected_hash: str | None = None
    uaepass: str | None = "confirmed"


@router.post("/{request_id}/decline")
def decline(company_id: str, request_id: str, body: DeclineIn, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    return _run(db, svc.decline, db, principal, company_id, request_id, decision=body.decision, reason=body.reason, expected_hash=body.expected_hash, uaepass=body.uaepass)


@router.post("/{request_id}/remind")
def remind(company_id: str, request_id: str, principal: Principal = Depends(member("returns.send_for_approval")), db: Session = Depends(get_db)):
    return _run(db, svc.remind_owner, db, principal, company_id, request_id)


@router.post("/{request_id}/release")
def release(company_id: str, request_id: str, lang: str = "en", principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    return _run(db, svc.release_for_filing, db, principal, company_id, request_id, lang=lang)


class FilingIn(BaseModel):
    outcome: str = "filed"
    filed_date: date | None = None
    authority_reference: str | None = None
    figures_as_filed: dict[str, int] | None = None
    self_filed_confirmed: bool = False
    receipt: dict | None = None


@router.post("/{request_id}/filing")
def record_filing(company_id: str, request_id: str, body: FilingIn, principal: Principal = Depends(member("filing.record", "returns.view")), db: Session = Depends(get_db)):
    rec = _run(db, svc.record_filing, db, principal, company_id, request_id, outcome=body.outcome, filed_date=body.filed_date, authority_reference=body.authority_reference, figures_as_filed=body.figures_as_filed, self_filed_confirmed=body.self_filed_confirmed, receipt=body.receipt)
    return svc.filing_dict(rec, principal.language) | {"confirmation": STRINGS["recorded_as_declared"]}


class FilingEditIn(BaseModel):
    filed_date: date | None = None
    authority_reference: str | None = None
    figures_as_filed: dict[str, int] | None = None


@router.patch("/filing/{record_id}")
def edit_filing(company_id: str, record_id: str, body: FilingEditIn, principal: Principal = Depends(member("filing.record", "returns.view")), db: Session = Depends(get_db)):
    rec = _run(db, svc.edit_filing, db, principal, company_id, record_id, filed_date=body.filed_date, authority_reference=body.authority_reference, figures_as_filed=body.figures_as_filed)
    return svc.filing_dict(rec, principal.language)


@router.post("/{request_id}/submit")
def submit(company_id: str, request_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    """Direct send path. The Submit control is never rendered in Phase 1; this call is refused by the adapter
    unless the live switch, the confirmed-live FTA row and a valid approval all hold."""
    req = svc.get_request(db, company_id, request_id)
    a = svc.current_approval(db, req)
    att = _run(db, adapter.submit, db, company_id=company_id, pack_id=req.pack_id, approval_id=a.id if a else None, caller_type="api", caller_key=principal.actor_key)
    return {"attempt_id": att.id, "status": att.status, "idempotency_key": att.idempotency_key}


@router.api_route("/records/{approval_id}", methods=["PUT", "PATCH", "DELETE"])
def edit_record_refused(company_id: str, approval_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    record_event(db, event_type="EDIT_DELETE_OVERRIDE_ATTEMPT_REFUSED", category="approval", outcome="refused", reason_code="RECORDS_READ_ONLY", actor_key=principal.actor_key, company_id=company_id, subject_type="approval", subject_id=approval_id)
    db.commit()
    raise Forbidden(STRINGS["records_read_only"]["en"], reason_code="RECORDS_READ_ONLY")


# --- E6-S2 delegate approval grants (Phase B, switched off per company) --------------------------


@grants_router.get("")
def list_grants(company_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    role = svc.role_on(principal, company_id)
    on = svc.phase_b_on(db, company_id)
    rows = list(db.scalars(select(DelegateApprovalGrant).where(DelegateApprovalGrant.company_id == company_id).order_by(DelegateApprovalGrant.created_at.desc())))
    if role == "delegate":
        rows = [g for g in rows if g.delegate_uuid == principal.identity_uuid]
    elif role not in svc.OWNER_LEVEL:
        rows = []
    holder = svc.holder_for(db, company_id, principal) if role in svc.OWNER_LEVEL else None
    from app.modules.companies.models import CompanyRole
    from app.modules.identity.models import Identity

    delegates = []
    if role in svc.OWNER_LEVEL:
        for r in db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status == "active")):
            ident = db.get(Identity, r.identity_uuid) if r.identity_uuid else None
            has = [g for g in rows if g.delegate_uuid == r.identity_uuid]
            chip = "no_approval_right" if not has else has[0].status
            delegates.append({"identity_uuid": r.identity_uuid, "name": ident.display_name if ident else None, "chip": chip, "end_date": has[0].end_date.isoformat() if has else None})
    from app.modules.delegates.service import authority_state

    state = authority_state(db, company_id)
    out = {"role": role, "phase_b_on": on, "locked": not on, "phase_b_off_text": STRINGS["phase_b_off"], "grants": [svc.grant_dict(g) for g in rows], "delegates": delegates, "defaults": svc.grant_defaults(db, company_id, holder) if role in svc.OWNER_LEVEL else None, "det_data": {"stale": state["stale"], "refreshed_at": state["det_refreshed_at"]}, "strings": _strings(principal.language)}
    db.commit()
    return out


class GrantIn(BaseModel):
    delegate_uuid: str
    tax_types: list[str]
    scope_option: str = "single_return"
    period_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    max_amount_fils: int | None = None
    submission_type: str = "return_pack"
    uaepass: str | None = "confirmed"


@grants_router.post("")
def create_grant(company_id: str, body: GrantIn, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    """Owner-only (NOT_OWNER_DELEGATE for delegates, NO_OWNER_ROLE without a matched Emirates ID); step-up;
    refused with RIGHT_SWITCHED_OFF while the per-company Phase B switch is OFF."""
    g = _run(db, svc.create_grant, db, principal, company_id, delegate_uuid=body.delegate_uuid, tax_types=body.tax_types, scope_option=body.scope_option, period_id=body.period_id, start_date=body.start_date, end_date=body.end_date, max_amount_fils=body.max_amount_fils, submission_type=body.submission_type, uaepass=body.uaepass)
    return svc.grant_dict(g)


@grants_router.post("/{grant_id}/revoke")
def revoke_grant(company_id: str, grant_id: str, principal: Principal = Depends(member("returns.view")), db: Session = Depends(get_db)):
    g = _run(db, svc.revoke_grant, db, principal, company_id, grant_id)
    return svc.grant_dict(g) | {"message": STRINGS["grant_revoked"]["en"].replace("[Name]", g.delegate_name or "")}


# --- DET approval compliance (K23 / K24) ----------------------------------------------------------


@det_router.get("")
def compliance(period: str | None = None, company_id: str | None = None, tax_type: str | None = None, approver_role: str | None = None, principal: Principal = Depends(require_staff("approval_compliance.view")), db: Session = Depends(get_db)):
    out = monitoring.compliance_view(db, period=period, company_id=company_id, tax_type=tax_type, approver_role=approver_role)
    record_event(db, event_type="VIEW_LOGGED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"view": "approval_compliance", "period": period})
    db.commit()
    return out | {"can_retry": any("config.change" in STAFF_PERMS.get(r, set()) for r in principal.staff_roles)}


@det_router.post("/run")
def run_job(principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    out = _run(db, monitoring.run_compliance_job, db)
    return {"k23": out["k23"], "k24": out["k24"], "exceptions_raised": out["exceptions_raised"]}


class ReviewIn(BaseModel):
    status: str
    note: str | None = None


@det_router.post("/exceptions/{exc_id}/review")
def review(exc_id: str, body: ReviewIn, principal: Principal = Depends(require_staff("approval_compliance.view")), db: Session = Depends(get_db)):
    e = _run(db, monitoring.review_exception, db, principal, exc_id, status=body.status, note_ref=body.note)
    return monitoring.exception_dict(e)


class RootCauseIn(BaseModel):
    root_cause: str
    fix: str


@det_router.post("/exceptions/{exc_id}/root-cause")
def root_cause(exc_id: str, body: RootCauseIn, principal: Principal = Depends(require_staff("approval_compliance.resolve")), db: Session = Depends(get_db)):
    e = _run(db, monitoring.record_root_cause, db, principal, exc_id, root_cause=body.root_cause, fix=body.fix)
    return monitoring.exception_dict(e) | {"flow_enabled": svc.flow_enabled(db), "wave_exit_blocked": monitoring.wave_exit_blocked(db)}


@ops_router.post("/sweep")
def sweep(principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    return _run(db, svc.sweep, db)
