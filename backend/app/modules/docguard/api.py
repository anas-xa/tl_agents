"""Document guard API (E5-S4): quarantine queue, simulated upload, owner review, ask-a-person, DET aggregates."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as bk
from app.modules.docguard import service as svc
from app.modules.docguard.strings import STRINGS

router = APIRouter(prefix="/api/companies/{company_id}/documents", tags=["docguard"])
staff_router = APIRouter(prefix="/api/docguard", tags=["docguard"])
routers = [router, staff_router]


def _strings(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in STRINGS.items()}


def _view_for(principal: Principal, company_id: str) -> str:
    role = bk.role_for(principal, company_id)
    if role in ("owner", "remote_owner"):
        return "full"
    if role == "delegate":
        return "full" if bk.has_function(principal, company_id, "uploads") else "neutral"
    if role == "compliance_reviewer":
        return "reviewer"
    return "neutral"


@router.get("/quarantine")
def quarantine(company_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    role = bk.role_for(principal, company_id)
    view = _view_for(principal, company_id)
    rows = svc.queue(db, company_id)
    lang = principal.language if principal.language in ("en", "ar") else "en"
    record_event(db, event_type="DOCUMENT_QUEUE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"view": view, "count": len(rows)})
    db.commit()
    return {"role": role, "view": view, "limits": svc.upload_limits(db), "strings": _strings(lang), "documents": [svc.doc_row(db, d, view=view, lang=lang) for d in rows], "can_review": role == "owner", "can_ask_person": role in ("owner", "remote_owner") or (role == "delegate" and bk.has_function(principal, company_id, "uploads"))}


@router.get("/upload-limits")
def limits(company_id: str, principal: Principal = Depends(require("documents.view")), db: Session = Depends(get_db)):
    return svc.upload_limits(db)


class UploadIn(BaseModel):
    name: str
    file_type: str
    size_bytes: int
    text: str = ""
    hidden_text: str | None = None
    metadata_text: str | None = None
    embedded_files: int = 0
    purpose: str = "tax"
    unreadable: bool = False
    reference_values: dict | None = None


@router.post("/quarantine/upload")
def upload(company_id: str, body: UploadIn, principal: Principal = Depends(require("uploads.manage")), db: Session = Depends(get_db)):
    """Simulated upload (JSON; text already extracted). Processing starts after upload; text is data only."""
    if bk.role_for(principal, company_id) == "delegate":
        bk.require_function(principal, company_id, "uploads")
    doc = svc.upload(db, company_id, principal, name=body.name, file_type=body.file_type, size_bytes=body.size_bytes, text=body.text, purpose=body.purpose, hidden_text=body.hidden_text, metadata_text=body.metadata_text, embedded_files=body.embedded_files, reference_values=body.reference_values, unreadable=body.unreadable)
    db.commit()
    return svc.doc_row(db, doc, view="full", lang=principal.language)


class ReviewIn(BaseModel):
    outcome: str
    note: str | None = None


@router.post("/quarantine/{doc_id}/open-review")
def open_review(company_id: str, doc_id: str, principal: Principal = Depends(require("docguard.review")), db: Session = Depends(get_db)):
    d = svc.open_review(db, company_id, doc_id, principal)
    db.commit()
    return svc.doc_row(db, d, view="full", lang=principal.language)


@router.post("/quarantine/{doc_id}/review")
def review(company_id: str, doc_id: str, body: ReviewIn, principal: Principal = Depends(require("docguard.review")), db: Session = Depends(get_db)):
    d = svc.clear_flag(db, company_id, doc_id, principal, role=bk.role_for(principal, company_id), outcome=body.outcome, note=body.note)
    db.commit()
    return svc.doc_row(db, d, view="full", lang=principal.language)


@router.post("/quarantine/{doc_id}/ask-person")
def ask_person(company_id: str, doc_id: str, principal: Principal = Depends(require("uploads.manage")), db: Session = Depends(get_db)):
    d = svc.ask_person(db, company_id, doc_id, principal, role=bk.role_for(principal, company_id), has_documents_function=bk.has_function(principal, company_id, "uploads"))
    db.commit()
    return svc.doc_row(db, d, view="full", lang=principal.language)


@staff_router.get("/aggregates")
def aggregates(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    return svc.aggregates(db)


@staff_router.get("/release-gate")
def release_gate(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    out = svc.run_guardrail_suite(db)
    db.commit()
    return out


@staff_router.get("/policy")
def policy(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return {"adapter_policy": svc.adapter_policy(db), "screening_rule_version": svc.SCREENING_RULE_VERSION, "upload_limits": svc.upload_limits(db), "credentials": "never visible; applied inside the adapter layer only"}
