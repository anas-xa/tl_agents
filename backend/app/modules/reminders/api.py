from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal, permissions_for
from app.modules.audit.service import record_event
from app.modules.reminders import service

router = APIRouter(prefix="/api", tags=["reminders"])


def _tick(db: Session, company_id: str) -> None:
    """On-access job tick: rebuild the company's schedule and send what is due (the scheduler calls run_due too)."""
    service.schedule_for_company(db, company_id)
    service.run_due(db, company_id=company_id)


@router.get("/companies/{company_id}/reminders")
def my_reminders(company_id: str, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    """The caller's in-portal reminder inbox (owner, remote owner and delegates for assigned functions)."""
    _tick(db, company_id)
    out = service.inbox(db, company_id, principal.identity_uuid)
    out["preferences"] = service.preferences_view(db, principal, company_id)
    if "reminders.manage" in permissions_for(db, principal, company_id):
        out["company_schedule"] = [r for r in service.company_reminders(db, company_id) if r["status"] in ("planned", "held", "retry_wait")][:50]
    record_event(db, event_type="REMINDERS_VIEWED", category="reminder", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id)
    db.commit()
    return out


@router.get("/companies/{company_id}/reminders/preferences")
def get_preferences(company_id: str, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    out = service.preferences_view(db, principal, company_id)
    db.commit()
    return out


class PrefBody(BaseModel):
    language: str | None = None
    channels: dict[str, bool] | None = None
    set_language: bool = False


@router.put("/companies/{company_id}/reminders/preferences")
def put_preferences(company_id: str, body: PrefBody, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    payload: dict = {"channels": body.channels or {}}
    if body.set_language or body.language is not None:
        payload["language"] = body.language
    out = service.set_preferences(db, principal, company_id, payload)
    service.schedule_for_company(db, company_id)
    db.commit()
    return out


@router.post("/companies/{company_id}/reminders/{reminder_id}/acknowledge")
def acknowledge(company_id: str, reminder_id: str, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    out = service.acknowledge(db, company_id, principal.identity_uuid, reminder_id)
    db.commit()
    return out


class RequestBody(BaseModel):
    requirement_type: str
    due_date: date | None = None
    reminder_date: date | None = None
    channel: str = "portal"


@router.post("/companies/{company_id}/reminders/requests")
def request_reminder(company_id: str, body: RequestBody, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    out = service.request_reminder(db, principal, company_id, requirement_type=body.requirement_type, due_date=body.due_date, reminder_date=body.reminder_date, channel=body.channel)
    db.commit()
    return out


@router.delete("/companies/{company_id}/reminders/requests/{request_id}")
def cancel_request(company_id: str, request_id: str, principal: Principal = Depends(require("reminders.view")), db: Session = Depends(get_db)):
    out = service.cancel_request(db, principal, company_id, request_id)
    db.commit()
    return out


@router.get("/companies/{company_id}/reminders/schedule")
def company_schedule(company_id: str, principal: Principal = Depends(require("reminders.manage")), db: Session = Depends(get_db)):
    _tick(db, company_id)
    out = {"reminders": service.company_reminders(db, company_id), "policy": service.policy(db), "channels": service.channel_states(db)}
    db.commit()
    return out


@router.get("/reminders/k30")
def k30(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return service.k30_summary(db)


@router.post("/reminders/run-due")
def run_due(principal: Principal = Depends(require_staff("config.change")), db: Session = Depends(get_db)):
    out = service.run_due(db)
    db.commit()
    return out
