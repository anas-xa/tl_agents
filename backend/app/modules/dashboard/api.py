from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require
from app.core.db import get_db
from app.modules.access.service import Principal
from app.modules.dashboard import service

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/companies/{company_id}/dashboard")
def company_dashboard(company_id: str, panels: str | None = None, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = service.dashboard(db, principal, company_id, panels=panels.split(",") if panels else None)
    service.remember_company(db, principal, company_id)
    db.commit()
    return out


@router.get("/companies/{company_id}/dashboard/panels/{panel}")
def one_panel(company_id: str, panel: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    """Per-panel reload (panels load independently; 'Try again' on one panel)."""
    out = service.dashboard(db, principal, company_id, panels=[panel])
    db.commit()
    return out["panels"][0] if out["panels"] else {}


class AccessBody(BaseModel):
    panel: str


@router.post("/companies/{company_id}/dashboard/request-access")
def request_access(company_id: str, body: AccessBody, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = service.request_access(db, principal, company_id, body.panel)
    db.commit()
    return out


class PanelSwitchBody(BaseModel):
    role_id: str
    panel: str
    visible: bool


@router.put("/companies/{company_id}/dashboard/delegate-panels")
def delegate_panels(company_id: str, body: PanelSwitchBody, principal: Principal = Depends(require("delegates.manage")), db: Session = Depends(get_db)):
    out = service.set_delegate_panel(db, principal, company_id, body.role_id, body.panel, body.visible)
    db.commit()
    return out


@router.post("/companies/{company_id}/dashboard/approval-cards/{card_id}/approve")
def approve_card(company_id: str, card_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = service.approve_card(db, principal, company_id, card_id)
    db.commit()
    return out


@router.post("/companies/{company_id}/remote-agent/{action}")
def remote_agent(company_id: str, action: str, request: Request, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = service.remote_agent_action(db, principal, company_id, action, request_id=request.headers.get("x-request-id"))
    db.commit()
    return out


@router.get("/me/remembered-company")
def get_remembered(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = service.remembered_company(db, principal)
    db.commit()
    return out


class RememberBody(BaseModel):
    company_id: str


@router.put("/me/remembered-company")
def put_remembered(body: RememberBody, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = service.remember_company(db, principal, body.company_id)
    db.commit()
    return out


@router.get("/me/portfolio")
def portfolio(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = service.portfolio(db, principal)
    db.commit()
    return out
