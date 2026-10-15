"""Phase map, gate register, integration checklist and SC3 'What is live' endpoints (E1-S7, E1-S8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden
from app.modules.access.service import Principal, permissions_for
from app.modules.audit.service import record_event
from app.modules.phases import service

admin_router = APIRouter(prefix="/api/admin", tags=["phases"])
company_router = APIRouter(prefix="/api/companies", tags=["phases"])
routers = [admin_router, company_router]


def _actor(p: Principal) -> str:
    return f"{p.actor_key}:{p.primary_role()}"


def require_switch_right():
    """Gate / switch writes: integrations.manage, or det.phase_switches for the DET pilot manager."""

    def _dep(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        held = permissions_for(db, principal, None)
        if "integrations.manage" in held or "det.phase_switches" in held:
            return principal
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"permission": "integrations.manage|det.phase_switches"})
        db.commit()
        raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION")

    return _dep


# --- phase map -------------------------------------------------------------------------------------


@admin_router.get("/phases")
def get_phases(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return service.phase_map(db)


class DemoIn(BaseModel):
    criteria: dict
    notes: str | None = None


@admin_router.post("/phases/{increment}/demo-done")
def demo_done(increment: str, body: DemoIn, principal: Principal = Depends(require_staff("phase_map.record_demo")), db: Session = Depends(get_db)):
    rec = service.record_demo_done(db, increment, recorded_by=principal.actor_key, criteria=body.criteria, notes=body.notes)
    db.commit()
    return {"id": rec.id, "increment": rec.increment, "recorded_at": rec.recorded_at.isoformat(), "gated_items_shown_off": rec.gated_items_shown_off}


@admin_router.post("/phases/{increment}/release")
def release(increment: str, principal: Principal = Depends(require_staff("phase_map.record_demo")), db: Session = Depends(get_db)):
    inc = service.release_increment(db, increment, approved_by=principal.actor_key)
    db.commit()
    return service.increment_dict(db, inc)


# --- gates -----------------------------------------------------------------------------------------


@admin_router.get("/gates")
def get_gates(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return [service.gate_dict(g) for g in service.current_gates(db)]


@admin_router.get("/gates/{gate_id}/history")
def get_gate_history(gate_id: str, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return [service.gate_dict(g) for g in service.gate_history(db, gate_id)]


class GateChange(BaseModel):
    status: str
    change_reason: str
    evidence_ref: str | None = None
    approved_by: str | None = None


@admin_router.post("/gates/{gate_id}/status")
def change_gate(gate_id: str, body: GateChange, principal: Principal = Depends(require_switch_right()), db: Session = Depends(get_db)):
    row = service.change_gate_status(db, gate_id, body.status, changed_by=_actor(principal), change_reason=body.change_reason, evidence_ref=body.evidence_ref, approved_by=body.approved_by)
    db.commit()
    return service.gate_dict(row)


# --- integrations ----------------------------------------------------------------------------------


@admin_router.get("/integrations")
def get_integrations(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    held = permissions_for(db, principal, None)
    detail = "integrations.manage" in held or "audit_trail.view" in held or "det.phase_switches" in held
    rows = service.current_rows(db)
    return {"rows": [service.row_dict(db, r, evidence_detail=detail) for r in rows], "evidence_detail": detail, "k11": service.k11_status(db), "k12_flags": service.k12_manual_path_flags(db), "outside_scope_switches": {k: bool(service.get_config(db, f"phases.switch.{k}.enabled", False)) for k in ("virtual_lawyer", "aml_channel", "remote_services_agent")}}


@admin_router.get("/integrations/{row_id}/history")
def get_row_history(row_id: str, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    held = permissions_for(db, principal, None)
    detail = "integrations.manage" in held or "audit_trail.view" in held
    return [service.row_dict(db, r, evidence_detail=detail) for r in service.row_history(db, row_id)]


class ItemIn(BaseModel):
    owner_name: str | None = None
    owner_role: str | None = None
    evidence_reference: str | None = None
    evidence_date: str | None = None
    approver_identity: str | None = None
    evidence_expires_at: str | None = None


@admin_router.post("/integrations/{row_id}/items/{item_id}/complete")
def complete_item(row_id: str, item_id: str, body: ItemIn, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    try:
        row = service.complete_item(db, row_id, item_id, changed_by=_actor(principal), **body.model_dump())
    finally:
        db.commit()
    return service.row_dict(db, row)


class StatusIn(BaseModel):
    status: str
    change_reason: str


@admin_router.post("/integrations/{row_id}/status")
def row_status(row_id: str, body: StatusIn, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    row = service.set_row_status(db, row_id, body.status, changed_by=_actor(principal), change_reason=body.change_reason)
    db.commit()
    return service.row_dict(db, row)


class SwitchIn(BaseModel):
    state: str
    reason: str


@admin_router.post("/integrations/switches/{switch_key}")
def set_switch(switch_key: str, body: SwitchIn, principal: Principal = Depends(require_switch_right()), db: Session = Depends(get_db)):
    try:
        sw = service.set_switch(db, switch_key, body.state, changed_by=_actor(principal), reason=body.reason)
    finally:
        db.commit()
    return {"switch_key": sw.switch_key, "state": sw.state, "row_id": sw.row_id, "changed_at": sw.changed_at.isoformat(), "history": sw.history}


@admin_router.post("/integrations/daily-check")
def daily_check(principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    out = service.daily_check(db, actor=_actor(principal))
    db.commit()
    return out


# --- SC3 ---------------------------------------------------------------------------------------------


@company_router.get("/{company_id}/whats-live")
def whats_live(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    roles = principal.roles_for(company_id)
    role = "delegate" if any(r.role == "delegate" for r in roles) and not any(r.role in ("owner", "remote_owner") for r in roles) else "owner"
    functions = [f for r in roles for f in (r.functions or [])]
    data = service.whats_live(db, role=role, functions=functions)
    db.commit()
    return data
