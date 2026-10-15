"""Data-link endpoints: /api/companies/{company_id}/links, /uploads, /tax-profile, /tax-link, /banks, /erp."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, SwitchedOff
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.datalinks import service as svc
from app.modules.datalinks.models import ErpConnectorLink, PullJob
from app.modules.datalinks.strings import s

links_router = APIRouter(prefix="/api/companies/{company_id}/links", tags=["datalinks"])
uploads_router = APIRouter(prefix="/api/companies/{company_id}/uploads", tags=["datalinks"])
tax_router = APIRouter(prefix="/api/companies/{company_id}", tags=["datalinks"])
staff_router = APIRouter(prefix="/api/datalinks", tags=["datalinks"])
routers = [links_router, uploads_router, tax_router, staff_router]


# --- links (E4-S6) ----------------------------------------------------------------------------------------------


@links_router.get("")
def links(company_id: str, lang: str = "en", principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = svc.link_rows(db, company_id, lang=lang)
    out["route"] = svc.route_status(db)
    out["banks"] = svc.list_banks(db)
    out["erp"] = svc.erp_register(db)
    out["erp_links"] = [svc.serialize_erp_link(db, link) for link in db.scalars(select(ErpConnectorLink).where(ErpConnectorLink.company_id == company_id))]
    out["remote_owner_read_only"] = svc.is_remote_owner_only(principal, company_id)
    out["can_manage"] = "links.manage" in {p for c in [principal] for p in _perms(db, c, company_id)}
    out["strings"] = {"bank_not_yet_available": s("bank.not_yet_available", lang), "through_provider": s("bank.through_provider", lang), "erp_not_available": s("erp.not_available", lang)}
    record_event(db, event_type="LINK_STATUS_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"rows": len(out["rows"])})
    db.commit()
    return out


def _perms(db: Session, principal: Principal, company_id: str) -> set[str]:
    from app.modules.access.service import permissions_for

    return permissions_for(db, principal, company_id)


class BankLinkIn(BaseModel):
    bank_id: str
    consent_id: str | None = None


@links_router.post("/bank", status_code=201)
def start_bank_link(company_id: str, body: BankLinkIn, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    if svc.is_remote_owner_only(principal, company_id):
        raise Forbidden("read-only status for an owner abroad", reason_code="REMOTE_OWNER_READ_ONLY")
    link = svc.start_bank_link(db, principal, company_id, body.bank_id, body.consent_id)
    db.commit()
    return {"link_id": link.link_id, "status": link.status}


@links_router.post("/bank/{bank_id}/notify-me")
def notify_me(company_id: str, bank_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    bank = svc.notify_me_when_available(db, principal, bank_id)
    db.commit()
    return {"bank_id": bank.bank_id, "notify": True, "note": "preference, not consent"}


@links_router.post("/pulls/schedule")
def schedule_pulls(company_id: str, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    jobs = svc.enqueue_scheduled_pulls(db, company_id, actor_key=principal.actor_key)
    db.commit()
    return {"scheduled": len(jobs)}


@links_router.post("/{link_id}/refresh")
def refresh(company_id: str, link_id: str, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    if svc.is_remote_owner_only(principal, company_id):
        raise Forbidden("read-only status for an owner abroad", reason_code="REMOTE_OWNER_READ_ONLY")
    if not get_config(db, "datalinks.openfinance.enabled", False):
        raise SwitchedOff("on-demand refresh is not available until the licensed route is live", reason_code="FEATURE_SWITCHED_OFF", details={"feature": "datalinks.openfinance"})
    return {"link_id": link_id, "queued": False}


@links_router.get("/{link_id}/technical-detail")
def technical_detail(company_id: str, link_id: str, principal: Principal = Depends(require_staff("cases.queue_alerts")), db: Session = Depends(get_db)):
    out = svc.technical_detail(db, principal, company_id, link_id)
    db.commit()
    return out


@links_router.get("/pull-jobs")
def pull_jobs(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    return [{"job_id": j.job_id, "consent_id": j.consent_id, "status": j.status, "scheduled_for": j.scheduled_for.isoformat(), "cancelled_at": j.cancelled_at.isoformat() if j.cancelled_at else None, "cancel_reason": j.cancel_reason, "result": j.result} for j in db.scalars(select(PullJob).where(PullJob.company_id == company_id).order_by(PullJob.created_at.desc()))]


# --- ERP (E4-S4) -------------------------------------------------------------------------------------------------


class ErpConnectIn(BaseModel):
    system_type: str


class DisconnectIn(BaseModel):
    reason: str | None = None


@links_router.get("/erp")
def erp(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    return {"register": svc.erp_register(db), "links": [svc.serialize_erp_link(db, link) for link in db.scalars(select(ErpConnectorLink).where(ErpConnectorLink.company_id == company_id))], "remote_owner_read_only": svc.is_remote_owner_only(principal, company_id)}


@links_router.post("/erp", status_code=201)
def connect_erp(company_id: str, body: ErpConnectIn, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    if svc.is_remote_owner_only(principal, company_id):
        raise Forbidden("an owner abroad cannot connect an accounting system in this phase; authorise a delegate", reason_code="REMOTE_OWNER_CANNOT_CONNECT")
    svc.require_function(db, principal, company_id, "connect_accounting_data", event="ERP_CONNECT_REFUSED")
    link = svc.connect_erp(db, principal, company_id, body.system_type)
    db.commit()
    return svc.serialize_erp_link(db, link)


@links_router.post("/erp/{link_id}/disconnect")
def disconnect_erp(company_id: str, link_id: str, body: DisconnectIn, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    svc.require_function(db, principal, company_id, "connect_accounting_data", event="ERP_DISCONNECT_REFUSED")
    link = svc.disconnect_erp(db, principal, company_id, link_id, body.reason)
    db.commit()
    return svc.serialize_erp_link(db, link)


# --- uploads (E4-S3 / E4-S4 file route) --------------------------------------------------------------------------


@uploads_router.get("")
def list_uploads(company_id: str, lang: str = "en", principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    rows = [svc.serialize_upload(db, u, lang) for u in svc.list_uploads(db, company_id)]
    return {"uploads": rows, "limits": svc.upload_limits(db), "manual_data_age": svc.manual_data_age(db, company_id), "label": s("upload.label", lang), "strings": {k: s(k, lang) for k in ("upload.you_uploaded", "upload.not_bank_link", "upload.ready", "upload.delete_warning", "bank.read_only")}}


@uploads_router.post("", status_code=201)
async def upload(
    company_id: str,
    file: UploadFile = File(...),
    kind: str = Form("bank_statement"),
    export_type: str | None = Form(None),
    bank_id: str | None = Form(None),
    bank_name: str | None = Form(None),
    account_ref: str | None = Form(None),
    period_start: str | None = Form(None),
    period_end: str | None = Form(None),
    purpose: str | None = Form(None),
    notice_acknowledged: bool = Form(False),
    notice_version: str | None = Form(None),
    principal: Principal = Depends(require("uploads.manage")),
    db: Session = Depends(get_db),
):
    svc.require_function(db, principal, company_id, "uploads", event="UPLOAD_REFUSED")
    data = await file.read()
    ps = date.fromisoformat(period_start) if period_start else None
    pe = date.fromisoformat(period_end) if period_end else None
    up = svc.create_upload(db, principal, company_id, file_name=file.filename or "upload", data=data, kind=kind, export_type=export_type, bank_id=bank_id, bank_name=bank_name, account_ref=account_ref, period_start=ps, period_end=pe, purpose=purpose, notice_acknowledged=notice_acknowledged, notice_version=notice_version)
    db.commit()
    return svc.serialize_upload(db, up, principal.language)


@uploads_router.get("/{upload_id}")
def upload_detail(company_id: str, upload_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    up = svc.get_upload(db, company_id, upload_id)
    out = svc.serialize_upload(db, up, principal.language)
    out["lines"] = svc.statement_lines(db, company_id, upload_id=upload_id, limit=200) if up.status == "ready" and up.kind == "bank_statement" else []
    record_event(db, event_type="UPLOAD_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="upload", subject_id=upload_id)
    db.commit()
    return out


@uploads_router.delete("/{upload_id}")
def delete_upload(company_id: str, upload_id: str, principal: Principal = Depends(require("uploads.manage")), db: Session = Depends(get_db)):
    roles = [r.role for r in principal.roles_for(company_id)]
    if "owner" not in roles and "remote_owner" not in roles:
        raise Forbidden("only the owner can delete an uploaded batch", reason_code="OWNER_ONLY")
    up = svc.get_upload(db, company_id, upload_id)
    svc.delete_upload(db, principal, up)
    db.commit()
    return svc.serialize_upload(db, up, principal.language)


@uploads_router.get("/{upload_id}/lines")
def upload_lines(company_id: str, upload_id: str, limit: int = 500, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    svc.get_upload(db, company_id, upload_id)
    return {"lines": svc.statement_lines(db, company_id, upload_id=upload_id, limit=limit), "label": "manual, unverified"}


# --- tax link and profile (E4-S5) -------------------------------------------------------------------------------


@tax_router.get("/tax-link")
def tax_link(company_id: str, lang: str = "en", principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    out = svc.tax_link_state(db, company_id, principal)
    out["strings"] = {"not_available": s("tax.not_available", lang), "cause": {"authority_not_responding": s("tax.cause.authority_not_responding", lang), "consent_expired": s("tax.cause.consent_expired", lang)}, "not_confirmed": s("tax.not_confirmed", lang)}
    out["remote_owner"] = svc.is_remote_owner_only(principal, company_id)
    db.commit()
    return out


@tax_router.get("/tax-profile")
def tax_profile(company_id: str, principal: Principal = Depends(require("dashboard.view")), db: Session = Depends(get_db)):
    profiles = svc.current_tax_profiles(db, company_id)
    record_event(db, event_type="TAX_PROFILE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"count": len(profiles)})
    db.commit()
    return {"profiles": [svc.serialize_tax_profile(p) for p in profiles], "rules": {"vat_due": get_config(db, "datalinks.tax.vat_due_rule", None), "ct_due": get_config(db, "datalinks.tax.ct_due_rule", None), "sbr_period_cutoff": get_config(db, "datalinks.tax.sbr_period_cutoff", None), "filing_frequencies": get_config(db, "datalinks.tax.filing_frequencies", []), "trn_pattern": get_config(db, "datalinks.tax.trn_pattern", None)}, "remote_owner": svc.is_remote_owner_only(principal, company_id)}


class TaxProfileIn(BaseModel):
    tax_type: str
    trn: str | None = None
    registration_status: str | None = None
    filing_status: str | None = None
    filed_date: str | None = None
    tax_period_start: str | None = None
    tax_period_end: str | None = None
    filing_frequency: str | None = None
    due_date_confirmed: bool = False
    due_date_override: str | None = None
    small_business_relief: list[dict] = []
    tax_group_id: str | None = None
    member_relationship: str | None = None
    source: str = "company_provided"
    receipt_upload_ref: str | None = None


@tax_router.put("/tax-profile")
def put_tax_profile(company_id: str, body: TaxProfileIn, principal: Principal = Depends(require("taxprofile.edit")), db: Session = Depends(get_db)):
    svc.require_function(db, principal, company_id, "tax_preparation", event="TAX_PROFILE_ENTRY_REFUSED")
    profile = svc.set_tax_profile(db, principal, company_id, body.model_dump())
    db.commit()
    return svc.serialize_tax_profile(profile)


class TaxLinkStartIn(BaseModel):
    consent_id: str | None = None


@tax_router.post("/tax-link/start")
def start_tax_link(company_id: str, body: TaxLinkStartIn, principal: Principal = Depends(require("links.manage")), db: Session = Depends(get_db)):
    if not get_config(db, "datalinks.tax.adapter.enabled", False):
        record_event(db, event_type="TAX_LINK_REFUSED", category="access", outcome="refused", reason_code="FEATURE_SWITCHED_OFF", actor_key=principal.actor_key, company_id=company_id)
        db.commit()
        raise SwitchedOff(s("tax.not_available", principal.language), reason_code="FEATURE_SWITCHED_OFF", details={"feature": "datalinks.tax.adapter", "gate": "E1-S8 FTA row"})
    link = svc.tax_link(db, company_id)
    link.status, link.route, link.consent_id = "not_linked", "fta_arrangement", body.consent_id
    db.commit()
    return svc.tax_link_state(db, company_id, principal)


# --- staff / aggregate ---------------------------------------------------------------------------------------------


@staff_router.get("/route-register")
def route_register(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    reg = svc.route_register(db)
    return {"route": svc.route_status(db), "register": {c.name: getattr(reg, c.name) for c in reg.__table__.columns} if reg else None, "banks": svc.list_banks(db)}


@staff_router.get("/k27")
def k27(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    """Aggregate K27 / K11 view: counts only (cell-size suppression applies in the DET module)."""
    from app.modules.companies.models import Company

    totals = {"companies": 0, "connector_fresh": 0, "connector_active": 0, "uploaded_fresh": 0, "uploaded_present": 0, "bank_not_available": 0, "manual_statement_on_file": 0}
    for c in db.scalars(select(Company)):
        rows = svc.link_rows(db, c.id)
        totals["companies"] += 1
        totals["connector_fresh"] += rows["k27"]["connector_line"]["numerator"]
        totals["connector_active"] += rows["k27"]["connector_line"]["denominator"]
        totals["uploaded_fresh"] += rows["k27"]["uploaded_line"]["numerator"]
        totals["uploaded_present"] += rows["k27"]["uploaded_line"]["denominator"]
        totals["bank_not_available"] += 1 if any(r["source_type"] == "bank" and r["badge"] == "not_available_yet" for r in rows["rows"]) else 0
        totals["manual_statement_on_file"] += 1 if rows["manual_uploads_line"]["count"] else 0
    from app.modules.kpis.suppression import min_group_size, suppress_count

    n = min_group_size(db)
    out = {k: suppress_count(v, n) for k, v in totals.items()}
    if totals["companies"] < n:  # filter blocking: a population below N publishes no numbers at all
        out = {k: suppress_count(1, n) for k in totals}
    out["k11_headline"] = "Not yet measurable: bank route not available"
    out["suppression_n"] = n
    return out
