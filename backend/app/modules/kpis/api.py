"""SC14 KPI endpoints (E9-S1). DET staff only; aggregates through the shared suppression engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal
from app.core.db import get_db
from app.core.errors import PlatformError, ValidationFailed
from app.modules.access.service import Principal, authorize
from app.modules.kpis import service

router = APIRouter(prefix="/api/det", tags=["kpis"])


def require_staff(permission: str):
    """Staff permission guard that keeps the refusal in the audit trail (the refusal never says whether data exists)."""

    def _dep(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        try:
            authorize(db, principal, permission, company_id=None)
        except PlatformError:
            db.commit()
            raise
        db.commit()
        return principal

    return _dep


class ExportBody(BaseModel):
    kpi_ids: list[str] | None = None
    period: str | None = None
    cohort: str | None = None
    payment_status: str | None = None
    dimension: str | None = None
    language: str | None = "en"
    level: str | None = "aggregate"


class MinGroupSizeBody(BaseModel):
    value: int | float | str
    reason: str
    consulted_compliance_lead: bool = False


@router.get("/kpis")
def get_kpis(period: str | None = None, cohort: str | None = None, payment_status: str | None = None, principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    out = service.dashboard(db, principal, period=period, cohort=cohort, payment_status=payment_status)
    db.commit()
    return out


@router.get("/kpis/runs")
def get_runs(limit: int = Query(200, ge=1, le=1000), principal: Principal = Depends(require_staff("det.kpi_runs.view")), db: Session = Depends(get_db)):
    out = service.calculation_runs(db, principal, limit)
    db.commit()
    return {"runs": out}


@router.post("/kpis/export")
def export_kpis(body: ExportBody, principal: Principal = Depends(require_staff("det.aggregates.export")), db: Session = Depends(get_db)):
    text, export_id = service.export_csv(db, principal, body.model_dump())
    db.commit()
    return Response(content=text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="det-pilot-kpis-{export_id}.csv"', "X-Export-Id": export_id})


@router.get("/kpis/{kpi_id}")
def get_kpi(kpi_id: str, dimension: str | None = None, period: str | None = None, cohort: str | None = None, payment_status: str | None = None, principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    try:
        out = service.kpi_detail(db, principal, kpi_id, dimension=dimension, period=period, cohort=cohort, payment_status=payment_status)
    except ValidationFailed:
        db.commit()  # keep the refusal log
        raise
    db.commit()
    return out


@router.get("/licences")
def lookup_licence(licence_number: str = Query("", max_length=40), principal: Principal = Depends(require_staff("det.per_licence.view")), db: Session = Depends(get_db)):
    """Per-licence operational lookup by exact licence number (no bulk listing)."""
    if not licence_number.strip():
        raise ValidationFailed("enter a licence number", reason_code="LICENCE_NUMBER_REQUIRED")
    try:
        out = service.per_licence_view(db, principal, licence_number.strip())
    except Exception:
        db.commit()
        raise
    db.commit()
    return {"results": [out["licence"]], "logged": True, "note": out["note"]}


@router.get("/licences/{licence_number}")
def licence_view(licence_number: str, principal: Principal = Depends(require_staff("det.per_licence.view")), db: Session = Depends(get_db)):
    try:
        out = service.per_licence_view(db, principal, licence_number)
    except Exception:
        db.commit()
        raise
    db.commit()
    return out


@router.get("/settings")
def get_settings(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return service.settings_view(db, principal)


@router.put("/settings/min-group-size")
def put_min_group_size(body: MinGroupSizeBody, principal: Principal = Depends(require_staff("det.min_group_size.manage")), db: Session = Depends(get_db)):
    out = service.set_min_group_size(db, principal, body.value, reason=body.reason, consulted_compliance_lead=body.consulted_compliance_lead)
    db.commit()
    return out
