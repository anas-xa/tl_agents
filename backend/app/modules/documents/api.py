"""Documents API (SC9): company document pack, render (HTML, browser prints), download log, sharing, issue;
public verification; staff revoke, signed-status layer and the two-administrator switch."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_principal, require, require_staff
from app.core.db import get_db
from app.core.errors import NotFound, PlatformError
from app.modules.access.service import Principal
from app.modules.documents import service as svc
from app.modules.documents.models import DeliveryLog, IssuedDocument
from app.modules.documents.strings import both

router = APIRouter(tags=["documents"])

def logged_db(db: Session = Depends(get_db)):
    """Same request session; refusals are logged before the error is returned (fail-closed audit entries persist)."""
    try:
        yield db
    except PlatformError:
        db.commit()
        raise



def _role(principal: Principal, company_id: str) -> str:
    return svc.role_on(principal, company_id) or principal.primary_role()


@router.get("/api/companies/{company_id}/documents")
def list_documents(company_id: str, principal: Principal = Depends(require("documents.view")), db: Session = Depends(logged_db)):
    role = _role(principal, company_id)
    docs = svc.visible_documents(db, principal, company_id)
    out = {"documents": [svc.doc_dict(db, d) for d in docs], "role": role, "empty": both("empty_list") if not docs else None, "can_issue": role == "owner", "issue_note": both("remote_issue_note") if role == "remote_owner" else None, "delegate_note": both("ask_owner_access") if role == "delegate" and not docs else None, "issuable_types": [{"doc_type": k, "label": {"en": v["label_en"], "ar": v["label_ar"]}, "class": v["class"]} for k, v in svc.sig_table(db).items() if v.get("issuable") and k not in ("auditors_report", "tax_pack_draft")]}
    db.commit()
    return out


@router.get("/api/companies/{company_id}/documents/{doc_id}")
def get_document(company_id: str, doc_id: str, principal: Principal = Depends(require("documents.view")), db: Session = Depends(logged_db)):
    doc = svc.get_document(db, principal, company_id, doc_id)
    svc.log_delivery(db, doc, event="opened", actor_name=principal.display_name, actor_role=_role(principal, company_id), actor_key=principal.actor_key)
    out = svc.doc_dict(db, doc, detail=True)
    db.commit()
    return out


@router.get("/api/companies/{company_id}/documents/{doc_id}/render", response_class=HTMLResponse)
def render(company_id: str, doc_id: str, lang: str = "both", principal: Principal = Depends(require("documents.view")), db: Session = Depends(logged_db)):
    doc = svc.get_document(db, principal, company_id, doc_id)
    svc.log_delivery(db, doc, event="opened", actor_name=principal.display_name, actor_role=_role(principal, company_id), actor_key=principal.actor_key, lang=lang)
    body = svc.render_view(db, doc, lang)
    db.commit()
    return HTMLResponse(body)


class DownloadIn(BaseModel):
    kind: str = "downloaded"
    lang: str | None = None


@router.post("/api/companies/{company_id}/documents/{doc_id}/download")
def download(company_id: str, doc_id: str, body: DownloadIn, principal: Principal = Depends(require("documents.download")), db: Session = Depends(logged_db)):
    doc = svc.get_document(db, principal, company_id, doc_id)
    out = svc.download(db, doc, actor_name=principal.display_name, actor_role=_role(principal, company_id), actor_key=principal.actor_key, kind=body.kind, lang=body.lang)
    db.commit()
    return out


@router.get("/api/companies/{company_id}/documents/{doc_id}/download-log")
def download_log(company_id: str, doc_id: str, principal: Principal = Depends(require("documents.view")), db: Session = Depends(logged_db)):
    doc = svc.get_document(db, principal, company_id, doc_id)
    rows = [{"event": r.event, "by": r.actor_name, "role": r.actor_role, "lang": r.lang, "at": r.at.isoformat()} for r in db.scalars(select(DeliveryLog).where(DeliveryLog.document_id == doc.id).order_by(DeliveryLog.at.desc()))]
    db.commit()
    return rows


class ShareIn(BaseModel):
    identity_uuid: str


@router.post("/api/companies/{company_id}/documents/{doc_id}/share")
def share(company_id: str, doc_id: str, body: ShareIn, principal: Principal = Depends(require("documents.share")), db: Session = Depends(logged_db)):
    doc = svc.get_document(db, principal, company_id, doc_id)
    svc.share(db, doc, principal, body.identity_uuid)
    db.commit()
    return svc.doc_dict(db, doc)


class IssueIn(BaseModel):
    doc_type: str
    pack_id: str | None = None


@router.post("/api/companies/{company_id}/documents/issue")
def issue(company_id: str, body: IssueIn, principal: Principal = Depends(require("documents.issue")), db: Session = Depends(logged_db)):
    try:
        if body.doc_type == "tax_pack_draft":
            if not body.pack_id:
                raise NotFound("pack not found", reason_code="NOT_FOUND")
            doc = svc.issue_tax_pack_draft(db, body.pack_id, principal)
            if doc.company_id != company_id:
                raise NotFound("pack not found", reason_code="NOT_FOUND")
        else:
            source = svc.build_source_record(db, company_id, body.doc_type) if svc.type_info(db, body.doc_type).get("issuable") and svc.type_info(db, body.doc_type).get("class") == "A" else {}
            doc = svc.issue_document(db, company_id, body.doc_type, source, principal)
    except Exception:
        db.commit()  # keep refusal and K28 check records
        raise
    db.commit()
    return svc.doc_dict(db, doc, detail=True)


@router.get("/api/documents/types")
def types(principal: Principal = Depends(get_principal), db: Session = Depends(logged_db)):
    return {"rule": "sig-v1", "types": svc.sig_table(db), "missing_type": "signature required (fail closed)"}


@router.get("/api/documents/verify/{code}")
def verify(code: str, request: Request, db: Session = Depends(logged_db)):
    try:
        out = svc.verify(db, code, ip=client_ip(request))
    except svc.RateLimited:
        db.commit()
        raise
    db.commit()
    return out


class RevokeIn(BaseModel):
    reason_code: str
    note: str | None = None
    written_request_ref: str | None = None
    requested_by_role: str | None = None


@router.post("/api/documents/{doc_id}/revoke")
def revoke(doc_id: str, body: RevokeIn, principal: Principal = Depends(require_staff("documents.revoke")), db: Session = Depends(logged_db)):
    doc = db.get(IssuedDocument, doc_id)
    if doc is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    svc.revoke(db, doc, reason_code=body.reason_code, note=body.note, request_ref=body.written_request_ref, requested_by_role=body.requested_by_role, actor_name=principal.display_name, actor_role="platform_security_admin", actor_key=principal.actor_key)
    db.commit()
    return svc.doc_dict(db, doc)


class SignedStatusIn(BaseModel):
    status: str
    instruction_source: str
    instruction_ref: str


@router.post("/api/documents/{doc_id}/signed-status")
def signed_status(doc_id: str, body: SignedStatusIn, principal: Principal = Depends(require_staff("documents.revoke")), db: Session = Depends(logged_db)):
    doc = db.get(IssuedDocument, doc_id)
    if doc is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    svc.set_signed_status(db, doc, status=body.status, source=body.instruction_source, ref=body.instruction_ref, actor_key=principal.actor_key)
    db.commit()
    return svc.doc_dict(db, doc)


class SwitchIn(BaseModel):
    enabled: bool
    reason: str


@router.post("/api/documents/switches/auditors-report")
def switch_request(body: SwitchIn, principal: Principal = Depends(require_staff("documents.switch")), db: Session = Depends(logged_db)):
    req = svc.request_switch(db, key=svc.AUDITORS_REPORT_SWITCH, new_state=body.enabled, reason=body.reason, requested_by=principal.identity_uuid)
    db.commit()
    return {"id": req.id, "status": req.status, "key": req.key}


@router.post("/api/documents/switches/requests/{request_id}/approve")
def switch_approve(request_id: str, principal: Principal = Depends(require_staff("documents.switch")), db: Session = Depends(logged_db)):
    try:
        req = svc.approve_switch(db, request_id, approver=principal.identity_uuid)
    except Exception:
        db.commit()
        raise
    db.commit()
    return {"id": req.id, "status": req.status, "key": req.key}
