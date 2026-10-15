"""Consent Centre endpoints (SC5): /api/companies/{company_id}/consents."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.consent import service as svc
from app.modules.consent.models import CONSENT_TYPES, ConsentRequest, Notification

router = APIRouter(prefix="/api/companies/{company_id}/consents", tags=["consent"])
staff_router = APIRouter(prefix="/api/consent", tags=["consent"])
routers = [router, staff_router]


class GrantIn(BaseModel):
    consent_type: str
    source: str | None = None
    data_types: list[str] = []
    account_ids: list[str] = []
    purpose: str
    expires_at: str
    recipient: str | None = None
    provider_name: str | None = None
    external_consent_id: str | None = None
    idempotency_key: str | None = None


class WithdrawIn(BaseModel):
    confirm: bool = True
    reason: str | None = None


class RequestIn(BaseModel):
    consent_type: str
    scope: dict = {}


class ProviderEventIn(BaseModel):
    external_consent_id: str | None = None
    consent_id: str | None = None
    external_status: str = "revoked"


def _retention_summary(db: Session) -> dict:
    return {
        "classes": get_config(db, "consent.retention.classes", []),
        "deletion_grace_days": get_config(db, "consent.retention.deletion_grace_days", None),
        "note": "No deletion date or instrument is stated until retention values are confirmed.",
    }


@router.get("")
def list_consents(company_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    svc.run_lifecycle(db, company_id)
    rights = svc.grant_rights(db, principal, company_id)
    rows = [svc.serialize_consent(db, c) for c in svc.list_consents(db, company_id)]
    record_event(db, event_type="CONSENTS_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"count": len(rows)})
    requests = [
        {"request_id": r.request_id, "consent_type": r.consent_type, "requester": r.requester_display_name, "requester_role": r.requester_role, "requested_at": r.requested_at.isoformat(), "expires_at": r.expires_at.isoformat(), "status": r.status}
        for r in db.scalars(select(ConsentRequest).where(ConsentRequest.company_id == company_id).order_by(ConsentRequest.requested_at.desc()))
    ]
    db.commit()
    return {
        "consents": rows,
        "rights": rights,
        "consent_types": list(CONSENT_TYPES),
        "controlled_lists": svc.controlled_lists(db),
        "wording_version": svc.wording_version(db),
        "retention": _retention_summary(db),
        "route": {"route_holder": get_config(db, "datalinks.route_holder", "licensed_provider_partner"), "openfinance_enabled": bool(get_config(db, "datalinks.openfinance.enabled", False)), "max_duration_months_bank": get_config(db, "datalinks.bank.consent_max_duration_months", 12), "max_duration_months": get_config(db, "consent.max_duration_months", 12)},
        "authority_rule": svc.authority_rule(db, company_id),
        "requests": requests,
        "loading_slow_threshold_seconds": get_config(db, "consent.loading_slow_threshold_seconds", 10),
    }


@router.get("/lists")
def lists(company_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    return {"controlled_lists": svc.controlled_lists(db), "wording_version": svc.wording_version(db), "consent_types": list(CONSENT_TYPES)}


@router.post("", status_code=201)
def grant(company_id: str, body: GrantIn, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    grantor = svc.require_consent_act(db, principal, company_id, "consent.grant", body.consent_type)
    db.commit()
    consent, created = svc.grant_consent(db, principal, company_id, body.model_dump(), grantor=grantor)
    db.commit()
    out = svc.serialize_consent(db, consent)
    out["created"] = created
    out["duplicate_of"] = None if created else consent.consent_id
    return out


@router.post("/{consent_id}/withdraw")
def withdraw(company_id: str, consent_id: str, body: WithdrawIn, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    svc.require_consent_act(db, principal, company_id, "consent.withdraw", consent.consent_type)
    db.commit()
    if consent.status == "pending":
        svc.cancel_pending(db, principal, consent)
        db.commit()
        return svc.serialize_consent(db, consent)
    w = svc.withdraw_consent(db, principal, consent, reason=body.reason)
    db.commit()
    out = svc.serialize_consent(db, consent)
    receipt = db.get(svc.ConsentReceipt, w.receipt_ref) if w.receipt_ref else None
    out["withdrawal_receipt"] = {"receipt_number": receipt.receipt_number, "en": receipt.content_en, "ar": receipt.content_ar, "template_version": receipt.template_version} if receipt else None
    return out


@router.post("/{consent_id}/cancel")
def cancel(company_id: str, consent_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    svc.require_consent_act(db, principal, company_id, "consent.withdraw", consent.consent_type)
    svc.cancel_pending(db, principal, consent)
    db.commit()
    return svc.serialize_consent(db, consent)


@router.post("/{consent_id}/resume")
def resume(company_id: str, consent_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    svc.require_consent_act(db, principal, company_id, "consent.grant", consent.consent_type)
    svc.resume_consent(db, principal, consent)
    db.commit()
    return svc.serialize_consent(db, consent)


@router.post("/{consent_id}/retry-revocation")
def retry_revocation(company_id: str, consent_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    w = db.scalar(select(svc.ConsentWithdrawal).where(svc.ConsentWithdrawal.consent_id == consent_id).order_by(svc.ConsentWithdrawal.created_at.desc()))
    if w is None:
        raise svc.NotFound("no withdrawal for this consent", reason_code="WITHDRAWAL_NOT_FOUND")
    svc.retry_source_revocation(db, w, actor_key=principal.actor_key)
    db.commit()
    return svc.timeline(db, consent)


@router.get("/{consent_id}/receipt")
def receipt(company_id: str, consent_id: str, kind: str = "grant", principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    r = svc.receipt_for(db, consent, kind)
    if r is None:
        raise svc.NotFound("receipt not found", reason_code="RECEIPT_NOT_FOUND")
    record_event(db, event_type="CONSENT_RECEIPT_VIEWED", category="data_access", actor_key=principal.actor_key, company_id=company_id, subject_type="consent_receipt", subject_id=r.receipt_id)
    db.commit()
    return {"receipt_id": r.receipt_id, "receipt_number": r.receipt_number, "kind": r.kind, "version": r.version, "template_version": r.template_version, "wording_version": r.wording_version, "en": r.content_en, "ar": r.content_ar, "created_at": r.created_at.isoformat(), "audit_entry_ref": r.audit_entry_ref}


@router.get("/{consent_id}/history")
def history(company_id: str, consent_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    return {"versions": svc.version_history(db, consent)}


@router.get("/{consent_id}/timeline")
def get_timeline(company_id: str, consent_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    consent = svc.get_consent(db, company_id, consent_id)
    return {"consent_id": consent_id, "status": consent.status, "timeline": svc.timeline(db, consent)}


@router.post("/requests", status_code=201)
def request_right(company_id: str, body: RequestIn, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    rights = svc.grant_rights(db, principal, company_id)
    if not rights["can_request"]:
        raise svc.Forbidden("this action is for delegates without the consent right", reason_code="REQUEST_NOT_APPLICABLE")
    req = svc.request_right(db, principal, company_id, body.consent_type, body.scope)
    db.commit()
    return {"request_id": req.request_id, "status": req.status, "expires_at": req.expires_at.isoformat(), "notified_count": req.notified_count, "granted": False}


@router.get("/notifications")
def my_notifications(company_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.company_id == company_id, Notification.recipient_identity_uuid == principal.identity_uuid).order_by(Notification.created_at.desc()).limit(100))
    return [{"notification_id": n.notification_id, "kind": n.kind, "channel": n.channel, "body_en": n.body_en, "body_ar": n.body_ar, "delivery_status": n.delivery_status, "created_at": n.created_at.isoformat(), "read_at": n.read_at.isoformat() if n.read_at else None} for n in rows]


@router.post("/lifecycle")
def lifecycle(company_id: str, principal: Principal = Depends(require("consent.view")), db: Session = Depends(get_db)):
    out = svc.run_lifecycle(db, company_id)
    db.commit()
    return out


# --- staff / integration endpoints -------------------------------------------------------------------------


@staff_router.post("/provider-events")
def provider_event(body: ProviderEventIn, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    """External revocation signal (provider webhook or poll result). Staff-only in the pilot."""
    consent = svc.external_revocation_signal(db, external_consent_id=body.external_consent_id, consent_id=body.consent_id, external_status=body.external_status, actor_key=principal.actor_key)
    db.commit()
    return svc.serialize_consent(db, consent)


@staff_router.get("/k13")
def k13(principal: Principal = Depends(require_staff("config.view")), db: Session = Depends(get_db)):
    return svc.k13_stats(db)
