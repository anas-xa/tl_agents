"""Hosting / residency endpoints (E1-S4): SC14 residency panel, owner statement, keys, egress, K12."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden
from app.modules.access.service import Principal, permissions_for
from app.modules.audit.service import record_event
from app.modules.hosting import egress, service
from app.modules.hosting.models import EgressAllowListChange, EgressBlockAlert
from app.modules.hosting.strings import both

router = APIRouter(prefix="/api/hosting", tags=["hosting"])
company_router = APIRouter(prefix="/api/companies", tags=["hosting"])
routers = [router, company_router]

READ_PERMS = ("residency.manage", "det.aggregates.view", "audit_trail.view")


def require_any_staff(*perms: str):
    def _dep(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        held = permissions_for(db, principal, None)
        if any(p in held for p in perms):
            return principal
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"permission": "|".join(perms)})
        db.commit()
        raise Forbidden(both("no_access")["en"], reason_code="NO_PERMISSION", details={"permission": "|".join(perms)})

    return _dep


@router.get("/residency-statement")
def residency_statement(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Owner residency statement (footer, consent screen, dashboard): any signed-in user."""
    return service.owner_residency_statement(db)


@router.get("/residency")
def residency(principal: Principal = Depends(require_any_staff(*READ_PERMS)), db: Session = Depends(get_db)):
    held = permissions_for(db, principal, None)
    data = service.residency_summary(db)
    data["viewer"] = {"can_manage": "residency.manage" in held, "counts_only": "residency.manage" not in held and "audit_trail.view" not in held}
    record_event(db, event_type="RESIDENCY_PANEL_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"state": data["state"]})
    db.commit()
    return data


@router.post("/residency/refresh")
def residency_refresh(principal: Principal = Depends(require_any_staff("residency.manage", "det.aggregates.view")), db: Session = Depends(get_db)):
    gen = service.generate_inventory(db, actor_key=principal.actor_key)
    decision = service.run_release_check(db, actor_key=principal.actor_key)
    db.commit()
    return {"generation": gen, "release_decision": service.decision_dict(decision), "summary": service.residency_summary(db)}


@router.get("/release-checks")
def release_checks(principal: Principal = Depends(require_any_staff(*READ_PERMS)), db: Session = Depends(get_db)):
    return [service.decision_dict(d) for d in service.release_decisions(db)]


@router.post("/release-checks")
def run_release_check(principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    d = service.run_release_check(db, actor_key=principal.actor_key)
    db.commit()
    return service.decision_dict(d)


@router.get("/checklist")
def checklist(principal: Principal = Depends(require_any_staff(*READ_PERMS)), db: Session = Depends(get_db)):
    doc = service.ensure_checklist(db)
    db.commit()
    return service.checklist_dict(doc)


# --- keys ---------------------------------------------------------------------------------------


@router.get("/keys")
def keys(principal: Principal = Depends(require_any_staff("residency.manage", "audit_trail.view")), db: Session = Depends(get_db)):
    return [service.key_dict(k) for k in service.list_keys(db)]


class RotateIn(BaseModel):
    fail_at_step: str | None = None
    resume: bool = False


@router.post("/keys/{key_id}/rotate")
def rotate(key_id: str, body: RotateIn, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    try:
        key = service.rotate_key(db, key_id, actor_key=principal.actor_key, fail_at_step=body.fail_at_step, resume=body.resume)
    finally:
        db.commit()
    return service.key_dict(key)


@router.post("/keys/{key_id}/rollback")
def rollback(key_id: str, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    key = service.rollback_rotation(db, key_id, actor_key=principal.actor_key)
    db.commit()
    return service.key_dict(key)


@router.post("/keys/{key_id}/compromise")
def compromise(key_id: str, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    role = "platform_security_admin" if principal.has_staff("platform_security_admin") else principal.primary_role()
    comp = service.declare_compromise(db, key_id, actor_key=principal.actor_key, actor_role=role)
    db.commit()
    return {"id": comp.id, "key_id": comp.key_id, "declared_at": comp.declared_at.isoformat(), "deadline_at": comp.deadline_at.isoformat(), "rotation_completed_at": comp.rotation_completed_at.isoformat() if comp.rotation_completed_at else None}


# --- egress -------------------------------------------------------------------------------------


def _change(c: EgressAllowListChange) -> dict:
    return {"change_id": c.change_id, "proposed_list": c.proposed_list, "change_hash": c.change_hash, "reason": c.reason, "requester_key": c.requester_key, "approver_1_key": c.approver_1_key, "approver_2_key": c.approver_2_key, "status": c.status, "created_at": c.created_at.isoformat(), "expires_at": c.expires_at.isoformat(), "applied_at": c.applied_at.isoformat() if c.applied_at else None}


@router.get("/egress")
def egress_state(principal: Principal = Depends(require_any_staff(*READ_PERMS)), db: Session = Depends(get_db)):
    egress.expire_pending_changes(db)
    db.commit()
    changes = list(db.scalars(select(EgressAllowListChange).order_by(desc(EgressAllowListChange.created_at)).limit(50)))
    return {"allow_list": sorted(egress.allowed_hosts(db)), "config_allow_list": egress.allowed_hosts(db) - set(h.lower() for h in egress.get_settings().outbound_allowlist), "policy_enabled": egress.policy_enabled(db), "changes": [_change(c) for c in changes], "alerts": egress.alert_counts(db)}


class ProposeIn(BaseModel):
    hosts: list[str]
    reason: str
    supersedes: str | None = None


@router.post("/egress/changes")
def propose(body: ProposeIn, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    c = egress.propose_allow_list_change(db, requester_key=principal.actor_key, hosts=body.hosts, reason=body.reason, supersedes=body.supersedes)
    db.commit()
    return _change(c)


class ApproveIn(BaseModel):
    change_hash: str
    fresh_auth: bool = True


@router.post("/egress/changes/{change_id}/approve")
def approve(change_id: str, body: ApproveIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if principal.has_staff("platform_security_admin", "qeonix_product_owner"):
        role = "qeonix_security_owner"
    elif principal.has_staff("det_admin"):
        role = "det_security_approver"
    else:
        raise Forbidden("only the Qeonix security owner or a DET security approver can approve", reason_code="NO_PERMISSION")
    try:
        c = egress.approve_allow_list_change(db, change_id, approver_key=principal.actor_key, approver_role=role, change_hash_seen=body.change_hash, fresh_auth=body.fresh_auth)
    finally:
        db.commit()
    return _change(c)


@router.post("/egress/changes/{change_id}/withdraw")
def withdraw(change_id: str, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    c = egress.withdraw_allow_list_change(db, change_id, requester_key=principal.actor_key)
    db.commit()
    return _change(c)


@router.get("/egress/alerts")
def alerts(principal: Principal = Depends(require_any_staff(*READ_PERMS)), db: Session = Depends(get_db)):
    held = permissions_for(db, principal, None)
    counts = egress.alert_counts(db)
    if "residency.manage" not in held and "audit_trail.view" not in held:
        return {"counts": counts, "alerts": None, "note": "counts only"}
    rows = list(db.scalars(select(EgressBlockAlert).order_by(desc(EgressBlockAlert.created_at)).limit(100)))
    return {"counts": counts, "alerts": [{"alert_id": a.alert_id, "host": a.host, "component_ref": a.component_ref, "status": a.status, "created_at": a.created_at.isoformat(), "ack_due_at": a.ack_due_at.isoformat(), "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None, "escalated_at": a.escalated_at.isoformat() if a.escalated_at else None} for a in rows]}


@router.post("/egress/alerts/{alert_id}/ack")
def ack(alert_id: str, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    a = egress.acknowledge_alert(db, alert_id, principal.actor_key)
    db.commit()
    return {"alert_id": a.alert_id, "status": a.status}


class GuardIn(BaseModel):
    url: str


@router.post("/egress/test")
def egress_test(body: GuardIn, principal: Principal = Depends(require_staff("residency.manage")), db: Session = Depends(get_db)):
    """Negative test hook: calls the guard against a URL (non-allow-listed hosts are refused and logged)."""
    host = egress.guard(body.url, db, component_ref="egress_negative_test")
    db.commit()
    return {"allowed": True, "host": host}


# --- K12 ----------------------------------------------------------------------------------------


@router.get("/k12/aggregate")
def k12_aggregate(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    data = service.k12_aggregate(db)
    db.commit()
    return data


@company_router.get("/{company_id}/k12")
def company_k12(company_id: str, request: Request, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    roles = [r.role for r in principal.roles_for(company_id)]
    viewer = "delegate" if "delegate" in roles and not any(r in roles for r in ("owner", "remote_owner")) else "owner"
    data = service.k12_status(db, company_id, viewer_role=viewer)
    data["viewer_role"] = viewer
    db.commit()
    return data
