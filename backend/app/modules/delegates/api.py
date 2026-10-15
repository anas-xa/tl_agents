"""Endpoints: delegates (SC11), per-case grants, SC15 activity list, hold status, auditor firewall, SC14 overview."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden
from app.core.time import utcnow
from app.modules.access.service import Principal, authorize, permissions_for, require_company_access
from app.modules.audit.service import record_event
from app.modules.companies.models import Company
from app.modules.config.service import get_config
from app.modules.delegates import service as svc
from app.modules.delegates.deps import require_company_action
from app.modules.delegates.models import PHASE_A_TOGGLES, PHASE_B_TOGGLES, TOGGLE_TO_RIGHT, FirewallRecord
from app.modules.delegates.strings import STRINGS

router = APIRouter(tags=["delegates"])


def _people_scope(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> tuple[Principal, str]:
    """Owners manage the list; delegates see only their own rights (settings.view_own)."""
    company_id = request.path_params["company_id"]
    require_company_access(db, principal, company_id)
    perms = permissions_for(db, principal, company_id)
    if "delegates.manage" in perms:
        scope = "all"
    elif "settings.view_own" in perms:
        scope = "own"
    else:
        authorize(db, principal, "delegates.manage", company_id=company_id)
        scope = "none"  # pragma: no cover - authorize raises
    db.commit()
    return principal, scope


def _toggle_meta(db: Session) -> list[dict]:
    phase_b = bool(get_config(db, "delegates.phase_b_switch", False))
    out = []
    for t in PHASE_A_TOGGLES:
        out.append({"toggle": t, "phase": "A", "locked": False, "default": False})
    for t in PHASE_B_TOGGLES:
        locked = not (phase_b and svc.delegate_right_enabled(db, TOGGLE_TO_RIGHT[t]))
        out.append({"toggle": t, "phase": "B", "locked": locked, "default": False, "locked_wording": STRINGS["not_available_owner_only"], "proposed_note": STRINGS["proposed_wording"]})
    return out


# --- SC11 delegates ----------------------------------------------------------------------------------


@router.get("/api/companies/{company_id}/delegates")
def list_delegates(company_id: str, scope: tuple[Principal, str] = Depends(_people_scope), db: Session = Depends(get_db)):
    principal, mode = scope
    state = svc.reconcile_company_authority(db, company_id)
    people = svc.list_people(db, company_id, own_identity=principal.identity_uuid if mode == "own" else None)
    out = {
        "company_id": company_id,
        "scope": mode,
        "people": people,
        "authority": state,
        "toggles": _toggle_meta(db),
        "limits": {"max_delegates_per_company": int(get_config(db, "delegates.max_delegates_per_company", 10)), "max_companies_per_delegate": int(get_config(db, "delegates.max_companies_per_delegate", 50)), "invitation_validity_days": int(get_config(db, "delegates.invitation_validity_days", 7))},
        "statement": STRINGS["delegation_statement"],
        "quarantine": svc.list_quarantine(db, company_id) if mode == "all" else [],
        "recent_changes": svc.recent_changes(db, company_id) if mode == "all" else svc.recent_changes(db, company_id, identity_uuid=principal.identity_uuid),
        "own": svc.delegate_rights_for(db, principal, company_id) if mode == "own" else None,
        "last_updated": utcnow().isoformat(),
    }
    db.commit()
    return out


class InviteIn(BaseModel):
    emirates_id: str = Field(min_length=1, max_length=40)
    entered_name: str | None = None
    email: str | None = None
    mobile: str | None = None
    toggles: list[str] = Field(default_factory=list)  # all off by default
    functions: list[str] | None = None


@router.post("/api/companies/{company_id}/delegates", status_code=201)
def invite(company_id: str, body: InviteIn, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    inv = svc.invite_delegate(db, principal, company_id, emirates_id=body.emirates_id, entered_name=body.entered_name, email=body.email, mobile=body.mobile, toggles=body.toggles, functions=body.functions)
    db.commit()
    return {"invitation_id": inv.id, "status": inv.status, "expires_at": inv.expires_at.isoformat(), "toggles": body.toggles, "entered_name": inv.entered_name}


@router.post("/api/companies/{company_id}/delegates/invitations/{invitation_id}/resend")
def resend(company_id: str, invitation_id: str, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    inv = svc.resend_invitation(db, principal, company_id, invitation_id)
    db.commit()
    return {"invitation_id": inv.id, "status": inv.status, "expires_at": inv.expires_at.isoformat()}


@router.post("/api/companies/{company_id}/delegates/invitations/{invitation_id}/withdraw")
def withdraw(company_id: str, invitation_id: str, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    inv = svc.withdraw_invitation(db, principal, company_id, invitation_id)
    db.commit()
    return {"invitation_id": inv.id, "status": inv.status}


class RightsIn(BaseModel):
    toggles: list[str]
    functions: list[str] | None = None


@router.patch("/api/companies/{company_id}/delegates/{role_id}")
def change_rights(company_id: str, role_id: str, body: RightsIn, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    result = svc.change_rights(db, principal, company_id, role_id, toggles=body.toggles, functions=body.functions)
    db.commit()
    return result


@router.delete("/api/companies/{company_id}/delegates/{role_id}")
def remove(company_id: str, role_id: str, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    result = svc.remove_delegate(db, principal, company_id, role_id)
    db.commit()
    return result


@router.post("/api/companies/{company_id}/delegates/{role_id}/suspend")
def suspend(company_id: str, role_id: str, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    r = svc.suspend_delegate(db, principal, company_id, role_id)
    db.commit()
    return {"role_id": r.id, "status": r.status}


@router.post("/api/companies/{company_id}/delegates/{role_id}/reinstate")
def reinstate(company_id: str, role_id: str, principal: Principal = Depends(require_company_action("delegates.manage")), db: Session = Depends(get_db)):
    r = svc.reinstate_delegate(db, principal, company_id, role_id)
    db.commit()
    return {"role_id": r.id, "status": r.status}


@router.get("/api/companies/{company_id}/delegates/changes")
def changes(company_id: str, principal: Principal = Depends(require("delegates.manage")), db: Session = Depends(get_db)):
    out = svc.recent_changes(db, company_id, limit=100)
    db.commit()
    return out


@router.get("/api/companies/{company_id}/delegates/quarantine")
def quarantine(company_id: str, status: str | None = "quarantined", principal: Principal = Depends(require("delegates.manage")), db: Session = Depends(get_db)):
    out = svc.list_quarantine(db, company_id, status=status or None)
    db.commit()
    return out


class DecisionIn(BaseModel):
    decision: str  # keep | reassign | discard  (= release | reassign | reject)
    reassign_to: str | None = None


@router.post("/api/companies/{company_id}/delegates/quarantine/{quarantine_id}/decide")
def decide(company_id: str, quarantine_id: str, body: DecisionIn, principal: Principal = Depends(require("delegates.manage")), db: Session = Depends(get_db)):
    q = svc.decide_quarantine(db, principal, company_id, quarantine_id, decision=body.decision, reassign_to=body.reassign_to)
    db.commit()
    return {"id": q.id, "status": q.status, "new_draft_ref": q.new_draft_ref, "decided_at": q.decided_at.isoformat()}


@router.get("/api/companies/{company_id}/delegates/me")
def my_rights(company_id: str, principal: Principal = Depends(require("settings.view_own")), db: Session = Depends(get_db)):
    out = svc.delegate_rights_for(db, principal, company_id)
    db.commit()
    return out


@router.get("/api/delegates/my-access-changes")
def my_access_changes(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = svc.my_access_changes(db, principal.identity_uuid)
    db.commit()
    return {"changes": out, "check_interval_seconds": int(get_config(db, "delegates.rights_cache_ttl_seconds", 30))}


@router.post("/api/delegates/my-access-changes/{change_id}/ack")
def ack_change(change_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    svc.acknowledge_change(db, principal.identity_uuid, change_id)
    db.commit()
    return {"ok": True}


@router.get("/api/delegates/history")
def delegate_history(company_id: str, principal: Principal = Depends(require_staff("delegates.history.view")), db: Session = Depends(get_db)):
    """Reviewer read-only delegate history (pseudonymous: labels only, no identity numbers)."""
    rows = svc.recent_changes(db, company_id, limit=200)
    record_event(db, event_type="DATA_ACCESS", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"view": "delegate_history", "rows": len(rows)})
    db.commit()
    return rows


# --- per-case grants ---------------------------------------------------------------------------------


class GrantIn(BaseModel):
    recipient_identity_uuid: str
    recipient_role: str
    case_ref: str
    purpose: str
    data_scope: list[str] = Field(default_factory=list)
    days: int | None = None


@router.get("/api/companies/{company_id}/grants")
def list_grants(company_id: str, principal: Principal = Depends(require("grants.create")), db: Session = Depends(get_db)):
    out = svc.list_grants(db, company_id)
    db.commit()
    return out


@router.post("/api/companies/{company_id}/grants", status_code=201)
def create_grant(company_id: str, body: GrantIn, principal: Principal = Depends(require_company_action("grants.create")), db: Session = Depends(get_db)):
    g = svc.create_grant(db, principal, company_id, recipient_identity_uuid=body.recipient_identity_uuid, recipient_role=body.recipient_role, case_ref=body.case_ref, purpose=body.purpose, data_scope=body.data_scope, days=body.days)
    db.commit()
    return {"grant_id": g.id, "case_ref": g.case_ref, "expires_at": g.expires_at.isoformat()}


@router.delete("/api/companies/{company_id}/grants/{grant_id}")
def revoke_grant(company_id: str, grant_id: str, principal: Principal = Depends(require("grants.create")), db: Session = Depends(get_db)):
    g = svc.revoke_grant(db, principal, company_id, grant_id)
    db.commit()
    return {"grant_id": g.id, "revoked_at": g.revoked_at.isoformat()}


@router.get("/api/companies/{company_id}/grants/case/{case_ref}")
def case_access(company_id: str, case_ref: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Specialist / auditor entry point: fail-closed check of the per-case grant (refusal logged)."""
    g = svc.require_grant(db, principal, company_id, case_ref)
    db.commit()
    return {"grant_id": g.id, "case_ref": g.case_ref, "purpose": g.purpose, "data_scope": g.data_scope, "expires_at": g.expires_at.isoformat()}


# --- SC15 activity ------------------------------------------------------------------------------------


@router.get("/api/companies/{company_id}/activity")
def activity(company_id: str, page: int = 1, kind: int | None = None, since: datetime | None = None, until: datetime | None = None, actor: str | None = None, outcome: str | None = None, lang: str | None = None, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = svc.activity_rows(db, principal, company_id, lang=(lang or principal.language or "en")[:2], page=max(page, 1), event_kind=kind, since=since, until=until, actor_key=actor, outcome=outcome)
    db.commit()
    return out


@router.get("/api/companies/{company_id}/activity/export")
def activity_export(company_id: str, lang: str | None = None, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = svc.export_activity(db, principal, company_id, lang=(lang or principal.language or "en")[:2])
    db.commit()
    return out


# --- hold state ---------------------------------------------------------------------------------------


@router.get("/api/companies/{company_id}/hold")
def hold_status(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    svc.check_hold_alerts(db)
    state = svc.reconcile_company_authority(db, company_id)
    db.commit()
    return state


class HoldIn(BaseModel):
    reason: str = "signatory_changed"


@router.post("/api/companies/{company_id}/hold/start")
def hold_start(company_id: str, body: HoldIn, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    hold = svc.start_signatory_change_hold(db, company_id, reason=body.reason, principal=principal)
    db.commit()
    return {"company_id": company_id, "hold_state": hold.hold_state, "hold_started_at": hold.hold_started_at.isoformat()}


@router.post("/api/companies/{company_id}/hold/lift")
def hold_lift(company_id: str, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    """DET onboarding support path: lifts after the DET record was corrected/confirmed (platform never edits DET data)."""
    hold = svc.lift_hold(db, company_id, lifted_by=f"det_support:{principal.actor_key[:8]}", principal=principal)
    db.commit()
    return {"company_id": company_id, "hold_state": hold.hold_state, "lifted_at": hold.lifted_at.isoformat() if hold.lifted_at else None}


# --- auditor firewall ---------------------------------------------------------------------------------


@router.get("/api/companies/{company_id}/firewall")
def firewall_list(company_id: str, principal: Principal = Depends(require("audit.view")), db: Session = Depends(get_db)):
    rows = [svc.firewall_row(r) for r in db.scalars(select(FirewallRecord).where(FirewallRecord.company_id == company_id).order_by(FirewallRecord.evaluated_at.desc()))]
    db.commit()
    return rows


class EvaluateIn(BaseModel):
    firm: str | None = None


@router.post("/api/companies/{company_id}/firewall/{engagement_id}/evaluate")
def firewall_evaluate(company_id: str, engagement_id: str, body: EvaluateIn, principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(get_db)):
    rec = svc.evaluate_firewall(db, principal.identity_uuid, company_id, engagement_id, firm=body.firm)
    db.commit()
    return svc.firewall_row(rec)


@router.post("/api/companies/{company_id}/firewall/{engagement_id}/declare")
def firewall_declare(company_id: str, engagement_id: str, principal: Principal = Depends(require_staff("engagements.view")), db: Session = Depends(get_db)):
    rec = svc.declare_independence(db, principal, engagement_id)
    db.commit()
    return svc.firewall_row(rec)


class FlagIn(BaseModel):
    code: str


@router.post("/api/companies/{company_id}/firewall/{engagement_id}/flag")
def firewall_flag(company_id: str, engagement_id: str, body: FlagIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Manual conflict flag by the owner (audit.view on the company) or a reviewer (audit_trail.view)."""
    is_owner = any(r.role in svc.OWNER_LEVEL for r in principal.roles_for(company_id))
    is_reviewer = "compliance_reviewer" in principal.staff_roles
    if not (is_owner or is_reviewer):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, company_id=company_id, details={"action": "firewall_flag"})
        db.commit()
        raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION")
    rec = svc.add_manual_conflict_flag(db, principal, engagement_id, code=body.code)
    db.commit()
    return svc.firewall_row(rec)


# --- SC14 delegation overview -------------------------------------------------------------------------


@router.get("/api/det/delegation-overview")
def delegation_overview(period_days: int = 30, principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    out = svc.delegation_overview(db, principal, period_days=90 if period_days > 30 else 30)  # fixed periods only
    db.commit()
    return out


@router.post("/api/det/delegation-overview/maintenance")
def maintenance(principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    """Daily jobs run on demand: invitation expiry, dormancy, hold alerts, authority reconciliation."""
    expired = svc.expire_invitations(db)
    dormancy = svc.run_dormancy_check(db)
    alerts = svc.check_hold_alerts(db)
    reconciled = 0
    for (cid,) in db.execute(select(Company.id)).all():
        svc.reconcile_company_authority(db, cid)
        reconciled += 1
    record_event(db, event_type="DELEGATION_MAINTENANCE_RUN", category="system", actor_key=principal.actor_key, details={"expired": expired, "alerts": alerts, "reconciled": reconciled, **dormancy})
    db.commit()
    return {"invitations_expired": expired, "hold_alerts": alerts, "companies_reconciled": reconciled, **dormancy}
