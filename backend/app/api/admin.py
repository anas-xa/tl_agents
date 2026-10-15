"""Configuration registers, rule register, audit trail viewer and staff-role administration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal, authorize
from app.modules.audit.models import AuditEvent, AuditPending
from app.modules.audit.service import export_events, query_events, verify_chain
from app.modules.config.service import config_history, list_config, list_rules, register_rule_version, set_config
from app.modules.identity.models import StaffRole
from app.modules.identity.service import create_staff_invitation, remove_staff_role

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _cfg(row) -> dict:
    return {
        "key": row.key, "version": row.version, "value": row.value, "unit": row.unit, "owner": row.owner, "status": row.status,
        "label": row.label, "description": row.description, "effective_from": row.effective_from.isoformat(), "changed_by": row.changed_by,
        "approved_by": row.approved_by, "change_reason": row.change_reason, "created_at": row.created_at.isoformat(),
    }


@router.get("/config")
def get_config_list(prefix: str | None = None, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return [_cfg(r) for r in list_config(db, prefix)]


@router.get("/config/{key}/history")
def get_config_history(key: str, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return [_cfg(r) for r in config_history(db, key)]


class ConfigChange(BaseModel):
    value: Any
    approved_by: str | None = None
    change_reason: str
    status: str | None = None
    label: str | None = None
    effective_from: date | None = None


@router.put("/config/{key}")
def change_config(key: str, body: ConfigChange, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    # Pilot-manager-owned values can be changed by the DET pilot manager; everything else needs config.change.
    if key.startswith(("pilot.", "fee.", "subscription.", "det.", "escalation.turnaround", "det_dashboard.")) and principal.has_staff("det_pilot_manager"):
        authorize(db, principal, "config.change_pilot")
    else:
        authorize(db, principal, "config.change")
    needs_second = key.startswith(("retention.", "audit_log.", "identity.")) or key.endswith(".enabled")
    entry = set_config(db, key, body.value, changed_by=principal.identity_uuid, approved_by=body.approved_by, change_reason=body.change_reason, status=body.status, label=body.label, effective_from=body.effective_from, require_second_approver=needs_second)
    from app.modules.audit.service import record_event

    record_event(db, event_type="CONFIG_CHANGED", category="config", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="config", subject_id=key, config_version=f"{key}@v{entry.version}", details={"value": body.value, "reason": body.change_reason, "approved_by": body.approved_by})
    db.commit()
    return _cfg(entry)


@router.get("/rules")
def get_rules(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return [
        {"rule_id": r.rule_id, "version": r.version, "title": r.title, "instrument": r.instrument, "source": r.source, "effective_from": r.effective_from.isoformat() if r.effective_from else None, "effective_to": r.effective_to.isoformat() if r.effective_to else None, "confirmed_by": r.confirmed_by, "status": r.status, "owner_role": r.owner_role, "parameters": r.parameters}
        for r in list_rules(db)
    ]


class RuleVersionIn(BaseModel):
    title: str
    version: str
    instrument: str | None = None
    source: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    confirmed_by: str | None = None
    status: str = "provisional"
    owner_role: str | None = None
    parameters: dict | None = None
    change_reason: str


@router.post("/rules/{rule_id}")
def new_rule_version(rule_id: str, body: RuleVersionIn, principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"change_reason", "title", "version"})
    row = register_rule_version(db, rule_id, body.title, version=body.version, **data)
    from app.modules.audit.service import record_event

    record_event(db, event_type="RULE_VERSION_ADDED", category="config", actor_key=principal.actor_key, subject_type="rule", subject_id=rule_id, config_version=f"{rule_id}@{body.version}", details={"reason": body.change_reason})
    db.commit()
    return {"rule_id": row.rule_id, "version": row.version}


# --- audit trail viewer (SC15) --------------------------------------------------------------------


def _event(ev: AuditEvent) -> dict:
    return {
        "event_id": ev.event_id, "occurred_at": ev.occurred_at.isoformat(), "event_type": ev.event_type, "category": ev.category,
        "outcome": ev.outcome, "reason_code": ev.reason_code, "actor_key": ev.actor_key, "actor_role": ev.actor_role, "company_id": ev.company_id,
        "licence_number": ev.licence_number, "subject_type": ev.subject_type, "subject_id": ev.subject_id, "details": ev.details, "language": ev.language,
        "config_version": ev.config_version, "corrects_event_id": ev.corrects_event_id, "hash": ev.hash,
    }


@router.get("/audit-trail")
def audit_trail(company_id: str | None = None, actor_key: str | None = None, category: str | None = None, event_type: str | None = None, since: datetime | None = None, until: datetime | None = None, limit: int = 100, offset: int = 0, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if principal.has_staff("det_admin") and not principal.has_staff("compliance_reviewer", "platform_security_admin"):
        authorize(db, principal, "audit_trail.view_summary")
        rows = query_events(db, company_id=None, actor_key=None, category=category, event_type=event_type, since=since, until=until, limit=limit, offset=offset)
        # DET administrator sees the summary: no company identifiers or details.
        out = [{k: v for k, v in _event(ev).items() if k not in ("company_id", "licence_number", "details", "subject_id", "actor_key")} for ev in rows]
    else:
        authorize(db, principal, "audit_trail.view")
        rows = query_events(db, company_id=company_id, actor_key=actor_key, category=category, event_type=event_type, since=since, until=until, limit=limit, offset=offset)
        out = [_event(ev) for ev in rows]
    from app.modules.audit.service import record_event

    record_event(db, event_type="AUDIT_TRAIL_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"filters": {"company_id": company_id, "category": category, "event_type": event_type}, "rows": len(out)})
    db.commit()
    return {"events": out, "count": len(out)}


@router.get("/audit-trail/integrity")
def audit_integrity(principal: Principal = Depends(require_staff("audit_trail.view")), db: Session = Depends(get_db)):
    intact, n = verify_chain(db)
    pending = db.scalar(select(AuditPending).where(AuditPending.replayed.is_(False)))
    return {"intact": intact, "events_checked": n, "pending_unreplayed": pending is not None}


class ExportIn(BaseModel):
    reason_code: str
    approved_by_key: str
    pseudonymised: bool = True
    filters: dict | None = None


@router.post("/audit-trail/export")
def audit_export(body: ExportIn, principal: Principal = Depends(require_staff("audit_trail.export")), db: Session = Depends(get_db)):
    export, rows = export_events(db, requested_by_key=principal.actor_key, approved_by_key=body.approved_by_key, reason_code=body.reason_code, pseudonymised=body.pseudonymised, filters=body.filters)
    db.commit()
    return {"export_id": export.export_id, "row_count": export.row_count, "rows": rows}


# --- staff roles ----------------------------------------------------------------------------------


class StaffInviteIn(BaseModel):
    role: str
    work_email: str
    approver: str
    reason: str | None = None
    scope: str | None = None
    entitlement_ref: str | None = None


@router.get("/staff-roles")
def staff_roles(principal: Principal = Depends(require_staff("staff_roles.manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(StaffRole).order_by(StaffRole.id))
    return [{"id": r.id, "role": r.role, "scope": r.scope, "work_email": r.work_email, "status": r.status, "requester": r.requester, "approver": r.approver, "bound": r.identity_uuid is not None, "invitation_expires_at": r.invitation_expires_at.isoformat() if r.invitation_expires_at else None, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/staff-roles")
def invite_staff(body: StaffInviteIn, principal: Principal = Depends(require_staff("staff_roles.manage")), db: Session = Depends(get_db)):
    row = create_staff_invitation(db, role=body.role, work_email=body.work_email, requester=principal.identity_uuid, approver=body.approver, reason=body.reason, scope=body.scope, entitlement_ref=body.entitlement_ref)
    db.commit()
    return {"id": row.id, "invitation_token": row.invitation_token, "expires_at": row.invitation_expires_at.isoformat()}


class StaffRemoveIn(BaseModel):
    approver: str
    reason: str | None = None


@router.delete("/staff-roles/{staff_role_id}")
def delete_staff(staff_role_id: int, body: StaffRemoveIn, principal: Principal = Depends(require_staff("staff_roles.manage")), db: Session = Depends(get_db)):
    remove_staff_role(db, staff_role_id, requester=principal.identity_uuid, approver=body.approver, reason=body.reason)
    db.commit()
    return {"ok": True}
