from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal, authorize
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.licences import service
from app.modules.licences.outbox import dispatch_in_new_session

router = APIRouter(prefix="/api", tags=["licences"])


def _intake_auth(request: Request, db: Session = Depends(get_db)) -> dict:
    """The DET feed authenticates with a shared secret header; staff may also post events (manual adapter)."""
    secret = get_config(db, "det_intake.shared_secret", None)
    header = request.headers.get("x-det-intake-secret")
    if secret and header and hmac.compare_digest(str(secret), header):
        return {"actor_key": "det_feed", "actor_role": "det_feed", "source": "det_feed"}
    principal = get_principal(request, db)
    authorize(db, principal, "integrations.manage")
    return {"actor_key": principal.actor_key, "actor_role": principal.primary_role(), "source": "manual_file"}


class IntakeBody(BaseModel):
    events: list[dict[str, Any]]


@router.post("/det/intake/events")
def intake_events(body: IntakeBody, background: BackgroundTasks, auth: dict = Depends(_intake_auth), db: Session = Depends(get_db)):
    """Channel-neutral intake. Each event is committed atomically before any downstream work is queued."""
    out = []
    for payload in body.events:
        try:
            ev = service.intake_event(db, payload, source=auth["source"], actor_key=auth["actor_key"], actor_role=auth["actor_role"])
            db.commit()  # per-licence commit: a failing event never rolls back an earlier one
            out.append({"event_id": ev.event_id, "status": ev.status, "held_reason": ev.held_reason, "quarantine_reason": ev.quarantine_reason, "licence_number": ev.licence_number})
        except Exception as exc:  # the failing event is rolled back; the batch is not atomic
            db.rollback()
            reason = getattr(exc, "reason_code", "INTAKE_EVENT_FAILED")
            out.append({"event_id": payload.get("event_id"), "status": "rejected", "error": reason, "message": str(exc)})
    # Downstream (subscription) work runs after the response: the handler never calls it.
    background.add_task(dispatch_in_new_session)
    return {"results": out, "accepted": sum(1 for r in out if r["status"] != "rejected")}


@router.get("/det/intake/status")
def intake_status(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return service.intake_status(db)


@router.get("/det/intake/held")
def intake_held(principal: Principal = Depends(require_staff("det.per_licence.view")), db: Session = Depends(get_db)):
    rows = service.held_events(db)
    record_event(db, event_type="INTAKE_HELD_LIST_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"rows": len(rows)})
    db.commit()
    return {"events": rows}


@router.get("/companies/{company_id}/licences")
def company_licences(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    rows = service.licences_for_company(db, company_id)
    record_event(db, event_type="LICENCE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"licences": len(rows)})
    db.commit()
    return {"licences": rows, "freshness_window_hours": service.freshness_window_hours(db)}
