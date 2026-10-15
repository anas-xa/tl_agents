from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, ValidationFailed
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.deadlines import service

router = APIRouter(prefix="/api", tags=["deadlines"])


def _cached(request: Request, response: Response, db: Session, body: dict) -> Any:
    tag = service.etag_for(body.get("items", []))
    secs = int(get_config(db, "deadlines.obligations.cache_seconds", 60) or 60)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": f"private, max-age={secs}"})
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = f"private, max-age={secs}"
    body["etag"] = tag
    return body


@router.get("/companies/{company_id}/obligations")
def company_obligations(company_id: str, request: Request, response: Response, include_done: bool = True, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    body = service.company_view(db, principal, company_id, include_done=include_done)
    record_event(db, event_type="DEADLINES_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"rows": len(body["items"]), "withheld": body["withheld_count"]}, fail_closed=True)
    db.commit()
    return _cached(request, response, db, body)


@router.get("/me/obligations")
def my_obligations(request: Request, response: Response, company_id: str | None = None, include_done: bool = False, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if company_id and company_id not in principal.company_ids():
        raise Forbidden("company not available to you", reason_code="NOT_YOUR_COMPANY")
    body = service.portfolio_rows(db, principal, company_filter=company_id, include_done=include_done)
    record_event(db, event_type="DEADLINES_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"rows": len(body["items"]), "companies": len(body["companies"]), "scope": "portfolio"}, fail_closed=True)
    db.commit()
    return _cached(request, response, db, body)


@router.get("/companies/{company_id}/obligations/{obligation_id}")
def obligation_detail(company_id: str, obligation_id: str, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    o = service.get_obligation(db, company_id, obligation_id)
    if o.obligation_type not in service.visible_types(db, principal, company_id):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="FUNCTION_NOT_ASSIGNED", actor_key=principal.actor_key, company_id=company_id, subject_type="obligation", subject_id=obligation_id)
        db.commit()
        raise Forbidden("this deadline is not shared with you", reason_code="FUNCTION_NOT_ASSIGNED")
    out = service.obligation_detail(db, o)
    if o.date_changed_at:  # the 'Date updated' chip ends once the deadline is opened
        o.date_changed_at = None
    db.commit()
    return out


class FiledBody(BaseModel):
    source: str
    filing_reference: str | None = None
    filed_date: str | None = None


@router.post("/companies/{company_id}/obligations/{obligation_id}/filed-evidence")
def filed_evidence(company_id: str, obligation_id: str, body: FiledBody, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    from app.modules.access.service import permissions_for

    if "filing.record" not in permissions_for(db, principal, company_id) and "uploads.manage" not in permissions_for(db, principal, company_id):
        raise Forbidden("you cannot record filing evidence for this company", reason_code="NO_PERMISSION")
    out = service.record_filed_evidence(db, principal, company_id, obligation_id, body.model_dump())
    db.commit()
    return out


class AuthorityBody(BaseModel):
    kind: str = "FTA_NOTICE"
    stated_date: str
    evidence_ref: str | None = None
    instrument_reference: str | None = None


@router.post("/companies/{company_id}/obligations/{obligation_id}/authority-date")
def authority_date(company_id: str, obligation_id: str, body: AuthorityBody, principal: Principal = Depends(require("filing.record")), db: Session = Depends(get_db)):
    out = service.record_authority_date(db, principal, company_id, obligation_id, body.model_dump())
    db.commit()
    return out


class NotifyBody(BaseModel):
    item_code: str


@router.post("/companies/{company_id}/obligations/notify-owner")
def notify_owner(company_id: str, body: NotifyBody, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    out = service.notify_owner(db, principal, company_id, body.item_code)
    db.commit()
    return out


class TaxDetailsBody(BaseModel):
    tax_type: str = "vat"
    trn: str | None = None
    tax_period_start: str | None = None
    tax_period_end: str | None = None
    filing_frequency: str | None = None


@router.post("/companies/{company_id}/obligations/tax-details")
def add_tax_details(company_id: str, body: TaxDetailsBody, principal: Principal = Depends(require("taxprofile.edit")), db: Session = Depends(get_db)):
    """SC4 inline fields ('Add tax details'): owner-entered, not verified. Saved through the tax profile (E4-S5)."""
    from app.modules.datalinks.service import set_tax_profile

    payload = {k: v for k, v in body.model_dump().items() if v not in (None, "")}
    payload["tax_type"] = "corporate_tax" if body.tax_type in ("ct", "corporate_tax") else "vat"
    payload["source"] = "company_provided"
    set_tax_profile(db, principal, company_id, payload)
    service.refresh_company(db, company_id, force=True)
    out = service.company_view(db, principal, company_id)
    db.commit()
    return out


@router.post("/companies/{company_id}/obligations/retry")
def retry(company_id: str, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    out = service.retry_company(db, company_id)
    db.commit()
    return out


@router.get("/companies/{company_id}/deadline-calendar")
def month_calendar(company_id: str, month: str, principal: Principal = Depends(require("deadlines.view")), db: Session = Depends(get_db)):
    try:
        y, m = (int(x) for x in month.split("-"))
    except ValueError as exc:
        raise ValidationFailed("month must be YYYY-MM", reason_code="MONTH_INVALID") from exc
    return service.month_calendar(db, y, m)


# --- reference maintenance (staff) ------------------------------------------------------------------------------


@router.get("/deadlines/reference")
def reference(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    from sqlalchemy import select

    from app.modules.deadlines.models import CalendarEntry

    entries = [{"id": e.id, "jurisdiction": e.jurisdiction, "name": {"en": e.name_en, "ar": e.name_ar}, "start_date": e.start_date.isoformat(), "end_date": e.end_date.isoformat(), "status": e.status, "approval_state": e.approval_state, "version": e.version, "source_reference": e.source_reference, "entered_by": e.entered_by, "approved_by": e.approved_by} for e in db.scalars(select(CalendarEntry).order_by(CalendarEntry.start_date))]
    return {"rules": service.list_rules(db), "history": service.rule_history(db), "calendar": entries, "calendar_versions": service.all_calendar_versions(db), "rules_version": service.rules_version_label(db)}


@router.post("/deadlines/rules")
def create_rule(body: dict[str, Any], principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    row = service.create_rule(db, body, actor_key=principal.actor_key)
    db.commit()
    return service.rule_dict(row)


class ApproveBody(BaseModel):
    approved_by: str


@router.post("/deadlines/rules/{rule_id}/activate")
def activate_rule(rule_id: str, body: ApproveBody, principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    row = service.activate_rule(db, rule_id, approved_by=body.approved_by, actor_key=principal.actor_key)
    db.commit()
    return service.rule_dict(row)


@router.post("/deadlines/calendar")
def add_holiday(body: dict[str, Any], principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    if not (principal.has_staff("det_pilot_manager", "platform_security_admin", "qeonix_product_owner")):
        raise Forbidden("only the named calendar maintainer may enter holidays", reason_code="NO_PERMISSION")
    row = service.add_calendar_entry(db, body, entered_by=principal.display_name, actor_key=principal.actor_key)
    db.commit()
    return {"id": row.id, "approval_state": row.approval_state}


@router.post("/deadlines/calendar/{entry_id}/approve")
def approve_holiday(entry_id: str, principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    if not (principal.has_staff("det_pilot_manager", "platform_security_admin", "qeonix_product_owner")):
        raise Forbidden("only a calendar maintainer may approve holidays", reason_code="NO_PERMISSION")
    out = service.approve_calendar_entry(db, entry_id, approved_by=principal.display_name, actor_key=principal.actor_key)
    db.commit()
    return out


@router.post("/deadlines/recalculate")
def recalculate(principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    out = service.run_recalculation_batch(db, reason="manual")
    db.commit()
    return out


@router.get("/deadlines/aggregates")
def aggregates(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return service.aggregates(db)
