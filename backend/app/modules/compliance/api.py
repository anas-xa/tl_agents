from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden
from app.modules.access.service import Principal, permissions_for
from app.modules.audit.service import record_event
from app.modules.compliance import service
from app.modules.compliance.strings import bi

router = APIRouter(prefix="/api", tags=["compliance"])


def _require_function(db: Session, principal: Principal, company_id: str) -> None:
    """Delegates see licence-linked requirements only with an assigned licence/compliance function."""
    from app.modules.deadlines.service import visible_types

    if "licence_renewal" not in visible_types(db, principal, company_id):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="FUNCTION_NOT_ASSIGNED", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"panel": "compliance"})
        db.commit()
        raise Forbidden("not shared with you", reason_code="FUNCTION_NOT_ASSIGNED")


@router.get("/companies/{company_id}/compliance")
def compliance(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    _require_function(db, principal, company_id)
    out = service.evaluate(db, company_id, principal=principal)
    perms = permissions_for(db, principal, company_id)
    out["can_prepare"] = "compliance.prepare" in perms
    out["can_approve"] = "compliance.approve" in perms
    out["prepare_disabled_reason"] = None if out["can_prepare"] else bi("remote.prepare_disabled")
    record_event(db, event_type="COMPLIANCE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id)
    db.commit()
    return out


class DeclareBody(BaseModel):
    requirement_type: str
    value_date: date
    reference: str | None = None
    evidence_ref: str | None = None


@router.post("/companies/{company_id}/compliance/declare")
def declare(company_id: str, body: DeclareBody, principal: Principal = Depends(require("compliance.prepare")), db: Session = Depends(get_db)):
    _require_function(db, principal, company_id)
    service.declare_value(db, principal, company_id, body.requirement_type, body.value_date, reference=body.reference, evidence_ref=body.evidence_ref)
    out = service.evaluate(db, company_id, principal=principal)
    db.commit()
    return out


class PackBody(BaseModel):
    output_type: str = "renewal_checklist"


@router.post("/companies/{company_id}/compliance/packs")
def prepare(company_id: str, body: PackBody, principal: Principal = Depends(require("compliance.prepare")), db: Session = Depends(get_db)):
    _require_function(db, principal, company_id)
    d = service.prepare_pack(db, principal, company_id, body.output_type)
    db.commit()
    return service.draft_dict(d)


class EditBody(BaseModel):
    changes: list[dict]


@router.post("/companies/{company_id}/compliance/packs/{draft_id}/edit")
def edit(company_id: str, draft_id: str, body: EditBody, principal: Principal = Depends(require("compliance.prepare")), db: Session = Depends(get_db)):
    d = service.edit_draft(db, principal, company_id, draft_id, body.changes)
    db.commit()
    return service.draft_dict(d)


@router.post("/companies/{company_id}/compliance/packs/{draft_id}/review")
def review(company_id: str, draft_id: str, principal: Principal = Depends(require("compliance.prepare")), db: Session = Depends(get_db)):
    d = service.mark_reviewed(db, principal, company_id, draft_id)
    db.commit()
    return service.draft_dict(d)


@router.post("/companies/{company_id}/compliance/packs/{draft_id}/approve")
def approve(company_id: str, draft_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    try:
        out = service.approve_draft(db, principal, company_id, draft_id)
    except Forbidden:
        db.commit()  # keep the denial log
        raise
    db.commit()
    return out


@router.post("/companies/{company_id}/compliance/packs/{draft_id}/discard")
def discard(company_id: str, draft_id: str, principal: Principal = Depends(require("compliance.prepare")), db: Session = Depends(get_db)):
    d = service.discard_draft(db, principal, company_id, draft_id)
    db.commit()
    return service.draft_dict(d)


@router.get("/compliance/aggregate")
def aggregate(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return service.det_aggregate(db)


@router.get("/compliance/k15")
def k15(principal: Principal = Depends(require_staff("agent_records.view")), db: Session = Depends(get_db)):
    return service.k15_summary(db)
