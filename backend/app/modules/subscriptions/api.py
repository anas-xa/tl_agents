from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, require_staff
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.modules.access.service import Principal, permissions_for
from app.modules.audit.service import record_event
from app.modules.licences.outbox import dispatch
from app.modules.subscriptions import service
from app.modules.subscriptions.models import BillingRequest, Case, Complaint, ReconciliationItem, Subscription

router = APIRouter(prefix="/api", tags=["subscriptions"])


def _sub_for_company(db: Session, company_id: str, subscription_id: str) -> Subscription:
    sub = db.get(Subscription, subscription_id)
    if sub is None or sub.company_id != company_id:
        raise NotFound("subscription not found", reason_code="SUBSCRIPTION_NOT_FOUND")
    return sub


def _role(principal: Principal, company_id: str) -> str:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else principal.primary_role()


# --- owner / delegate views -------------------------------------------------------------------------------


@router.get("/companies/{company_id}/subscription")
def company_subscription(company_id: str, principal: Principal = Depends(require("subscription.view")), db: Session = Depends(get_db)):
    service.require_switch(db, "views", True)
    perms = permissions_for(db, principal, company_id)
    out = service.company_subscription_view(db, company_id, can_change="subscription.change" in perms, role=_role(principal, company_id))
    record_event(db, event_type="SUBSCRIPTION_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=out["role"], company_id=company_id, details={"licences": len(out["licences"])})
    db.commit()
    return out


@router.get("/companies/{company_id}/subscription/terms")
def terms(company_id: str, principal: Principal = Depends(require("subscription.view")), db: Session = Depends(get_db)):
    return service.terms_view(db, principal.language)


class OptOutIn(BaseModel):
    request_id: str
    reason_code: str
    free_text: str | None = None
    understood: bool = False


@router.post("/companies/{company_id}/subscription/{subscription_id}/opt-out")
def opt_out(company_id: str, subscription_id: str, body: OptOutIn, principal: Principal = Depends(require("subscription.change")), db: Session = Depends(get_db)):
    """Owner only (step-up enforced by the permission). Delegates can never be granted this in the pilot."""
    sub = _sub_for_company(db, company_id, subscription_id)
    if not body.understood:
        raise Forbidden("confirm that you understand what will stop", reason_code="UNDERSTANDING_REQUIRED")
    case, created = service.open_case(db, sub, action="opt_out", request_id=body.request_id, reason_code=body.reason_code, actor_key=principal.actor_key, actor_role=_role(principal, company_id), language=principal.language, assurance_level=principal.assurance_level, free_text=body.free_text)
    db.commit()
    return {"case": service.case_dict(case), "already_requested": not created, "message": "already requested" if not created else "request received, DET decides"}


class RefundIn(BaseModel):
    request_id: str
    reason_code: str
    free_text: str | None = None


@router.post("/companies/{company_id}/subscription/{subscription_id}/refund-request")
def refund_request(company_id: str, subscription_id: str, body: RefundIn, principal: Principal = Depends(require("subscription.change")), db: Session = Depends(get_db)):
    sub = _sub_for_company(db, company_id, subscription_id)
    case, created = service.open_case(db, sub, action="refund", request_id=body.request_id, reason_code=body.reason_code, actor_key=principal.actor_key, actor_role=_role(principal, company_id), language=principal.language, assurance_level=principal.assurance_level, free_text=body.free_text)
    db.commit()
    return {"case": service.case_dict(case), "already_requested": not created, "message": "Request received. DET decides.", "expected_response_working_days": service.get_config(db, "refund.response_time_working_days", 10), "expected_response_label": "illustrative, to be confirmed with DET"}


@router.post("/companies/{company_id}/subscription/{subscription_id}/cases/{case_id}/cancel")
def cancel_case(company_id: str, subscription_id: str, case_id: str, principal: Principal = Depends(require("subscription.change")), db: Session = Depends(get_db)):
    _sub_for_company(db, company_id, subscription_id)
    case = db.get(Case, case_id)
    if case is None or case.subscription_id != subscription_id:
        raise NotFound("request not found", reason_code="CASE_NOT_FOUND")
    service.cancel_case(db, case, actor_key=principal.actor_key)
    db.commit()
    return service.case_dict(case)


class ComplaintIn(BaseModel):
    licence_number: str | None = None
    subscription_id: str | None = None
    category: str
    description: str
    preferred_language: str = "ar"
    contact_channel: str | None = "portal"
    related_module: str | None = None
    related_date: date | None = None


@router.post("/companies/{company_id}/complaints")
def open_complaint(company_id: str, body: ComplaintIn, principal: Principal = Depends(require("complaints.open")), db: Session = Depends(get_db)):
    row = service.open_complaint(db, company_id=company_id, licence_number=body.licence_number, subscription_id=body.subscription_id, category=body.category, description=body.description, preferred_language=body.preferred_language, contact_channel=body.contact_channel, actor_key=principal.actor_key, actor_role=_role(principal, company_id), related_module=body.related_module, related_date=body.related_date)
    db.commit()
    return {"complaint": service.complaint_dict(row), "message": "We will reply by {date}", "reply_by": row.reply_by.isoformat()}


@router.get("/companies/{company_id}/complaints")
def list_complaints(company_id: str, principal: Principal = Depends(require("subscription.view")), db: Session = Depends(get_db)):
    return {"complaints": [service.complaint_dict(c) for c in db.scalars(select(Complaint).where(Complaint.company_id == company_id).order_by(Complaint.received_at.desc()))]}


@router.get("/companies/{company_id}/welcome")
def welcome(company_id: str, principal: Principal = Depends(require("subscription.view")), db: Session = Depends(get_db)):
    perms = permissions_for(db, principal, company_id)
    out = service.welcome_view(db, company_id=company_id, actor_key=principal.actor_key, language=principal.language, assurance_level=principal.assurance_level, can_change="subscription.change" in perms, role=_role(principal, company_id))
    db.commit()
    return out


class WelcomeIn(BaseModel):
    action: str  # done | later
    language_choice: str | None = None
    reminder_channel: str | None = None


@router.post("/companies/{company_id}/welcome")
def welcome_done(company_id: str, body: WelcomeIn, principal: Principal = Depends(require("subscription.view")), db: Session = Depends(get_db)):
    run = service.welcome_record(db, company_id=company_id, actor_key=principal.actor_key, action=body.action, language_choice=body.language_choice, reminder_channel=body.reminder_channel)
    db.commit()
    return {"status": run.status, "language_choice": run.language_choice, "reminder_channel": run.reminder_channel}


# --- staff: queue, billing hook, payments, reconciliation -------------------------------------------------


@router.post("/subscriptions/process-queue")
def process_queue(principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    n = dispatch(db)
    return {"consumed": n}


@router.post("/subscriptions/{subscription_id}/billing/request")
def billing_request(subscription_id: str, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise NotFound("subscription not found", reason_code="SUBSCRIPTION_NOT_FOUND")
    req = service.request_billing(db, sub, actor_key=principal.actor_key)
    db.commit()
    return service.billing_dict(req, show_amounts=True)


class ReadbackIn(BaseModel):
    det_record: dict[str, Any] | None = None  # manual adapter / sandbox: the DET billing record as read
    reason_code: str | None = None  # required for admin re-reads


@router.post("/subscriptions/billing/{request_id}/read-back")
def billing_readback(request_id: str, body: ReadbackIn, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    req = db.get(BillingRequest, request_id)
    if req is None:
        raise NotFound("billing request not found", reason_code="BILLING_REQUEST_NOT_FOUND")
    service.read_back(db, req, body.det_record, actor_key=principal.actor_key)
    db.commit()
    return service.billing_dict(req, show_amounts=True)


@router.post("/det/billing/{request_id}/re-read")
def admin_reread(request_id: str, body: ReadbackIn, principal: Principal = Depends(require_staff("det.billing.reconcile")), db: Session = Depends(get_db)):
    """DET admin re-read: reason code required, identity logged, rate-limited."""
    req = db.get(BillingRequest, request_id)
    if req is None:
        raise NotFound("billing request not found", reason_code="BILLING_REQUEST_NOT_FOUND")
    if not body.reason_code:
        raise Forbidden("a reason code is required", reason_code="REASON_CODE_REQUIRED")
    service.admin_reread_allowed(db, req, principal.actor_key)
    record_event(db, event_type="BILLING_ADMIN_REREAD", category="billing", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="billing_request", subject_id=req.id, reason_code=body.reason_code)
    service.read_back(db, req, body.det_record, actor_key=principal.actor_key)
    db.commit()
    return {"status": req.status, "collection_status": req.collection_status, "read_attempts": req.read_attempts}


class PaymentIn(BaseModel):
    payment_transaction_id: str
    amount_fils: int
    type: str = "payment"
    payment_idempotency_key: str | None = None
    source_timestamp: str | None = None
    billing_line_id: str | None = None
    invoice_id: str | None = None
    invoice_lines: list[dict[str, Any]] | None = None
    refund_reason: str | None = None
    reference: str | None = None
    channel: str | None = None


@router.post("/subscriptions/billing/payments")
def payment_event(body: PaymentIn, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    pe = service.record_payment(db, body.model_dump(), actor_key=principal.actor_key)
    db.commit()
    return {"payment_id": pe.id, "allocation_status": pe.allocation_status, "type": pe.type}


@router.get("/det/subscriptions/aggregates")
def det_aggregates(principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    out = service.det_aggregates(db, actor_key=principal.actor_key)
    db.commit()
    return out


@router.get("/det/billing/reconciliation")
def reconciliation(principal: Principal = Depends(require_staff("det.billing.reconcile")), db: Session = Depends(get_db)):
    return {"items": service.reconciliation_list(db)}


class ResolveIn(BaseModel):
    reason_code: str


@router.post("/det/billing/reconciliation/{item_id}/resolve")
def resolve(item_id: str, body: ResolveIn, principal: Principal = Depends(require_staff("det.billing.reconcile")), db: Session = Depends(get_db)):
    item = db.get(ReconciliationItem, item_id)
    if item is None:
        raise NotFound("item not found", reason_code="RECONCILIATION_NOT_FOUND")
    service.resolve_reconciliation(db, item, actor_key=principal.actor_key, reason_code=body.reason_code)
    db.commit()
    return {"id": item.id, "status": item.status}


# --- staff: cases and complaints --------------------------------------------------------------------------


@router.get("/det/cases")
def det_cases(principal: Principal = Depends(require_staff("det.cases.decide")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Case).order_by(Case.received_at.desc()).limit(200))
    return {"cases": [{**service.case_dict(c), "subscription_id": c.subscription_id} for c in rows]}


class DecisionIn(BaseModel):
    decision: str  # confirm | reject
    reason: str | None = None
    effective_at: date | None = None


@router.post("/det/cases/{case_id}/decision")
def det_case_decision(case_id: str, body: DecisionIn, principal: Principal = Depends(require_staff("det.cases.decide")), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise NotFound("case not found", reason_code="CASE_NOT_FOUND")
    service.det_case_decision(db, case, decision=body.decision, actor_key=principal.actor_key, reason=body.reason, effective_at=body.effective_at)
    db.commit()
    return service.case_dict(case)


@router.post("/det/cases/{case_id}/needs-det-action")
def needs_det_action(case_id: str, principal: Principal = Depends(require_staff("integrations.manage")), db: Session = Depends(get_db)):
    """Simulated hook timeout (no confirmation after the configured wait): raises the DET alert."""
    case = db.get(Case, case_id)
    if case is None:
        raise NotFound("case not found", reason_code="CASE_NOT_FOUND")
    service.mark_needs_det_action(db, case)
    db.commit()
    return service.case_dict(case)


@router.get("/det/complaints")
def det_complaints(principal: Principal = Depends(require_staff("complaints.handle")), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Complaint).order_by(Complaint.reply_by, Complaint.received_at)))
    record_event(db, event_type="COMPLAINT_QUEUE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role="det_complaint_handler", details={"rows": len(rows)})
    db.commit()
    return {"complaints": [service.complaint_dict(c, handler=True) for c in rows], "sla_working_days": service.get_config(db, "complaint.reply_period_working_days", 5)}


class ComplaintStatusIn(BaseModel):
    status: str
    reason_code: str
    interim_due_date: date | None = None


@router.post("/det/complaints/{complaint_id}/status")
def complaint_status(complaint_id: str, body: ComplaintStatusIn, principal: Principal = Depends(require_staff("complaints.handle")), db: Session = Depends(get_db)):
    row = db.get(Complaint, complaint_id)
    if row is None:
        raise NotFound("complaint not found", reason_code="COMPLAINT_NOT_FOUND")
    service.set_complaint_status(db, row, status=body.status, reason_code=body.reason_code, actor_key=principal.actor_key, interim_due_date=body.interim_due_date)
    db.commit()
    return service.complaint_dict(row, handler=True)
