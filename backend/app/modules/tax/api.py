"""Tax API (E5-S2): profile, VAT and corporate-tax calculations per period, review, adjustments, escalations."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.core.errors import NotFound
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as bk
from app.modules.tax import service as svc
from app.modules.tax.models import EscalationRecord
from app.modules.tax.strings import STRINGS

router = APIRouter(prefix="/api/companies/{company_id}/tax", tags=["tax"])
staff_router = APIRouter(prefix="/api/tax", tags=["tax"])
routers = [router, staff_router]


def _strings(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in STRINGS.items()}


class ProfileIn(BaseModel):
    trn: str | None = None
    vat_registered: bool | None = None
    vat_period_type: str | None = None
    ct_status: str | None = None
    first_ct_period_start: date | None = None
    sbr_election: str | None = None
    revenue_fils: int | None = None
    revenue_source: str | None = None
    related_party_declared: bool | None = None
    mne_group_eur_750m: bool | None = None


@router.get("/profile")
def get_profile(company_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    p = svc.get_profile(db, company_id)
    db.commit()
    return svc.profile_dict(p)


@router.put("/profile")
def put_profile(company_id: str, body: ProfileIn, principal: Principal = Depends(require("taxprofile.edit")), db: Session = Depends(get_db)):
    p = svc.update_profile(db, company_id, principal, **body.model_dump())
    db.commit()
    return svc.profile_dict(p)


def _view(db: Session, company_id: str, tax_type: str, period_id: str, principal: Principal) -> dict:
    role = bk.role_for(principal, company_id)
    profile = svc.get_profile(db, company_id)
    calc = svc.latest(db, company_id, tax_type, period_id)
    base = {"company_id": company_id, "tax_type": tax_type, "period_id": period_id, "role": role, "strings": _strings(principal.language), "can_prepare": role in ("owner", "delegate") and bk.has_function(principal, company_id, "tax_preparation"), "view_only_reason": None if bk.has_function(principal, company_id, "tax_preparation") or role == "remote_owner" else STRINGS["view_only_no_function"]["en"], "profile": svc.profile_dict(profile)}
    record_event(db, event_type="CALCULATION_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"tax_type": tax_type, "period_id": period_id})
    if calc is None:
        start, end = svc.period_for(db, company_id, period_id)
        empty_reason = "add_trn" if (tax_type == "vat" and not profile.trn) else "confirm_to_calculate"
        return base | {"calculation": None, "empty": empty_reason, "period_start": start.isoformat(), "period_end": end.isoformat(), "needs_review_count": len(bk.excluded_transactions(db, company_id, start, end))}
    svc.check_stale(db, calc)
    return base | {"calculation": svc.calc_dict(db, calc, role=role, summary_only=(role == "remote_owner"))}


@router.get("/vat/{period_id}")
def get_vat(company_id: str, period_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    out = _view(db, company_id, "vat", period_id, principal)
    db.commit()
    return out


@router.post("/vat/{period_id}")
def run_vat(company_id: str, period_id: str, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    bk.require_function(principal, company_id, "tax_preparation")
    calc = svc.calculate_vat(db, company_id, period_id, actor=principal)
    db.commit()
    return svc.calc_dict(db, calc)


class CtIn(BaseModel):
    accounting_profit_fils: int | None = None
    revenue_fils: int | None = None
    revenue_source: str | None = None
    prior_revenues: list[int] | None = None
    adjustments: list[dict] | None = None
    loss_cf_fils: int | None = None
    sbr_election: str | None = None
    pro_rate: bool | None = None


@router.get("/ct/{period_id}")
def get_ct(company_id: str, period_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    out = _view(db, company_id, "ct", period_id, principal)
    db.commit()
    return out


@router.post("/ct/{period_id}")
def run_ct(company_id: str, period_id: str, body: CtIn | None = None, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    bk.require_function(principal, company_id, "tax_preparation")
    body = body or CtIn()
    calc = svc.calculate_ct(db, company_id, period_id, actor=principal, **body.model_dump())
    db.commit()
    return svc.calc_dict(db, calc)


@router.post("/{tax_type}/{period_id}/mark-reviewed")
def mark_reviewed(company_id: str, tax_type: str, period_id: str, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    calc = svc.mark_reviewed(db, company_id, tax_type, period_id, principal)
    db.commit()
    return svc.calc_dict(db, calc)


@router.get("/{tax_type}/{period_id}/versions")
def versions(company_id: str, tax_type: str, period_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(svc.CalculationResult).where(svc.CalculationResult.company_id == company_id, svc.CalculationResult.tax_type == tax_type, svc.CalculationResult.period_id == period_id).order_by(svc.CalculationResult.version))
    return [{"id": c.id, "version": c.version, "state": c.state, "rule_version": c.rule_version, "review_status": c.review_status, "created_at": c.created_at.isoformat()} for c in rows]


class AdjustmentIn(BaseModel):
    kind: str
    label: str
    amount_fils: int
    reason: str
    related_party: bool = False
    adjustment_class: str = "person_entered"


@router.post("/ct/{period_id}/adjustments")
def add_adjustment(company_id: str, period_id: str, body: AdjustmentIn, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    bk.require_function(principal, company_id, "tax_preparation")
    a = svc.add_adjustment(db, company_id, period_id, principal, **body.model_dump())
    db.commit()
    return {"id": a.id, "class": a.adjustment_class, "review_status": a.review_status, "held_for_specialist": a.held_for_specialist}


class EscalateIn(BaseModel):
    note: str | None = None


@router.post("/{tax_type}/{period_id}/escalate")
def escalate(company_id: str, tax_type: str, period_id: str, body: EscalateIn | None = None, principal: Principal = Depends(require("escalation.open")), db: Session = Depends(get_db)):
    calc = svc.latest(db, company_id, tax_type, period_id)
    if calc is None:
        raise NotFound("no calculation to escalate", reason_code="NOT_FOUND")
    esc = svc._escalate(db, calc, "manual", amount_fils=None, note=(body.note if body else None) or "owner asked a human specialist", actor_key=principal.actor_key)
    db.commit()
    return {"id": esc.id, "status": esc.status, "expected_response_hours": esc.expected_response_hours}


@staff_router.get("/escalations")
def list_escalations(principal: Principal = Depends(require_staff("cases.queue.tax")), db: Session = Depends(get_db)):
    """Tax specialist queue: escalated calculations (metadata, inputs and rule versions; consent recorded by E8)."""
    rows = list(db.scalars(select(EscalationRecord).order_by(EscalationRecord.created_at.desc())))
    record_event(db, event_type="ESCALATIONS_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role="tax_specialist", details={"count": len(rows)})
    db.commit()
    return [{"id": e.id, "company_id": e.company_id, "tax_type": e.tax_type, "period_id": e.period_id, "trigger_id": e.trigger_id, "status": e.status, "amount_fils": e.amount_fils, "rule_version": e.rule_version, "expected_response_hours": e.expected_response_hours, "calculation_id": e.calculation_id, "created_at": e.created_at.isoformat()} for e in rows]
