from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal, permissions_for
from app.modules.cohorts import service
from app.modules.cohorts.models import CohortChangeRequest
from app.modules.config.service import get_config, rule_params

router = APIRouter(prefix="/api", tags=["cohorts"])


@router.get("/det/cohort/config")
def cohort_config(principal: Principal = Depends(require_staff("det.cohort.view")), db: Session = Depends(get_db)):
    return {
        "waves": service.waves(db),
        "enrolment_modes": ["opt_in", "default_on_with_opt_out"],
        "default_enrolment_mode": get_config(db, "cohort.enrolment_mode", "opt_in"),
        "default_on_mode_enabled": service.default_on_mode_enabled(db),
        "stale_block_threshold_hours": service.stale_threshold_hours(db),
        "stale_warning_hours": get_config(db, "sc14.stale_warning_hours", 24),
        "suppression_n": service.suppression_n(db),
        "allow_shift_default": get_config(db, "cohort.allow_shift_default", False),
        "eligibility_rule": rule_params(db, "cohort_eligibility_v1", {}),
        "exclusion_categories": get_config(db, "cohort.exclusion_categories", []),
        "phase_modules": get_config(db, "cohort.phase_modules", {}),
        "usage_definition": get_config(db, "usage.definition", {}),
        "can_approve": "det.cohort.approve" in permissions_for(db, principal, None),
        "can_manage": "det.cohort.manage" in permissions_for(db, principal, None),
    }


@router.get("/det/cohort")
def list_cohorts(principal: Principal = Depends(require_staff("det.cohort.view")), db: Session = Depends(get_db)):
    return {"cohorts": service.list_cohorts(db)}


class CohortIn(BaseModel):
    name: str
    code: str
    wave: str
    size_limit: int | None = None
    start_date: date | None = None
    modules: list[str] | None = None
    criteria: dict | None = None
    enrolment_mode: str = "opt_in"
    reason: str | None = None
    status: str = "draft"


@router.post("/det/cohort")
def create_cohort(body: CohortIn, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    row = service.create_cohort(db, name=body.name, code=body.code, wave=body.wave, actor_key=principal.actor_key, size_limit=body.size_limit, start_date=body.start_date, modules=body.modules, criteria=body.criteria, enrolment_mode=body.enrolment_mode, reason=body.reason, status=body.status)
    db.commit()
    return service.cohort_dict(row)


@router.get("/det/cohort/changes")
def list_changes(state: str | None = "pending", principal: Principal = Depends(require_staff("det.cohort.view")), db: Session = Depends(get_db)):
    stmt = select(CohortChangeRequest).order_by(CohortChangeRequest.created_at.desc()).limit(200)
    if state:
        stmt = stmt.where(CohortChangeRequest.state == state)
    return {"changes": [service.change_dict(r) for r in db.scalars(stmt)]}


@router.get("/det/cohort/{cohort_id}")
def cohort_detail(cohort_id: str, principal: Principal = Depends(require_staff("det.cohort.view")), db: Session = Depends(get_db)):
    out = service.cohort_detail(db, cohort_id, actor_key=principal.actor_key)
    db.commit()
    return out


class VersionIn(BaseModel):
    reason: str
    name: str | None = None
    wave: str | None = None
    size_limit: int | None = None
    start_date: date | None = None
    modules: list[str] | None = None
    selection_criteria: dict | None = None
    enrolment_mode: str | None = None
    status: str | None = None


@router.post("/det/cohort/{cohort_id}/versions")
def new_version(cohort_id: str, body: VersionIn, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    row = service.new_version(db, cohort_id, actor_key=principal.actor_key, reason=body.reason, **body.model_dump(exclude={"reason"}))
    db.commit()
    return service.cohort_dict(row)


@router.post("/det/cohort/{cohort_id}/preview")
def preview(cohort_id: str, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    out = service.preview(db, cohort_id)
    db.commit()
    return out


class ChangeIn(BaseModel):
    licence_numbers: list[str] = []
    action: str
    request_id: str
    reason: str
    effective_at: datetime | None = None
    allow_shift: bool | None = None
    target_wave: str | None = None


@router.post("/det/cohort/{cohort_id}/changes")
def request_change(cohort_id: str, body: ChangeIn, principal: Principal = Depends(require_staff("det.cohort.manage")), db: Session = Depends(get_db)):
    eff = None
    if body.effective_at is not None:
        eff = body.effective_at.astimezone(UTC).replace(tzinfo=None) if body.effective_at.tzinfo else body.effective_at
    rows = service.request_change(db, cohort_id=cohort_id, licence_numbers=body.licence_numbers, action=body.action, request_id=body.request_id, reason=body.reason, requester_key=principal.actor_key, effective_at=eff, allow_shift=body.allow_shift, target_wave=body.target_wave)
    db.commit()
    return {"changes": [service.change_dict(r) for r in rows]}


@router.post("/det/cohort/changes/{change_id}/approve")
def approve(change_id: str, principal: Principal = Depends(require_staff("det.cohort.approve")), db: Session = Depends(get_db)):
    row = service.approve_change(db, change_id, approver_key=principal.actor_key)
    db.commit()
    return service.change_dict(row)


class RejectIn(BaseModel):
    reason: str


@router.post("/det/cohort/changes/{change_id}/reject")
def reject(change_id: str, body: RejectIn, principal: Principal = Depends(require_staff("det.cohort.approve")), db: Session = Depends(get_db)):
    row = service.reject_change(db, change_id, approver_key=principal.actor_key, reason=body.reason)
    db.commit()
    return service.change_dict(row)


# --- company side -----------------------------------------------------------------------------------------


@router.get("/companies/{company_id}/cohort")
def company_cohort(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    return {"licences": service.company_cohort_view(db, company_id), "enrolment_mode_default": get_config(db, "cohort.enrolment_mode", "opt_in")}


class InterestIn(BaseModel):
    licence_number: str


@router.post("/companies/{company_id}/cohort/interest")
def register_interest(company_id: str, body: InterestIn, principal: Principal = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    row = service.register_interest(db, company_id=company_id, licence_number=body.licence_number, actor_key=principal.actor_key, language=principal.language)
    db.commit()
    return {"licence_number": row.licence_number, "status": row.status, "registered_at": row.registered_at.isoformat(), "note": "candidate only; DET selects, no subscription is created"}
