"""Draft pack API (E5-S3): list/create/get/send-for-review/record-review/edit/export/hold decisions."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.db import get_db
from app.core.errors import Forbidden, ValidationFailed
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as bk
from app.modules.drafts import service as svc
from app.modules.drafts.models import DraftPack
from app.modules.drafts.strings import STRINGS

router = APIRouter(prefix="/api/companies/{company_id}/drafts", tags=["drafts"])


def _strings(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in STRINGS.items()}


def _pack_for(db: Session, company_id: str, pack_id: str) -> DraftPack:
    pack = svc.get_pack(db, pack_id)
    if pack.company_id != company_id:
        raise Forbidden("You do not have access to this company's drafts.", reason_code="NOT_YOUR_COMPANY")
    return pack


def _guard_role(principal: Principal, company_id: str) -> str:
    role = bk.role_for(principal, company_id)
    if role == "remote_owner":
        raise Forbidden("Draft returns are not available to you yet. You can view your dashboard and reminders.", reason_code="REMOTE_OWNER_NO_DRAFTS")
    return role


@router.get("")
def list_packs(company_id: str, principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    role = _guard_role(principal, company_id)
    rows = list(db.scalars(select(DraftPack).where(DraftPack.company_id == company_id).order_by(DraftPack.created_at.desc())))
    for p in rows:
        svc.check_out_of_date(db, p)
    record_event(db, event_type="DRAFTS_LISTED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"count": len(rows)})
    db.commit()
    out = [{"id": p.id, "tax_type": p.tax_type, "period_id": p.period_id, "version": p.version, "review_status": p.review_status, "review_status_label": svc.STATUS_LABELS.get(p.review_status), "superseded": p.superseded, "on_hold": p.on_hold if role == "owner" else False, "held_delegate": p.held_delegate_name if role == "owner" else None, "created_at": p.created_at.isoformat(), "is_demo": p.is_demo, "ai_label": {"en": p.ai_label_en, "ar": p.ai_label_ar}} for p in rows if (role == "owner" or not p.on_hold)]
    return {"role": role, "packs": out, "strings": _strings(principal.language), "held_count": sum(1 for p in rows if p.on_hold) if role == "owner" else 0}


class CreateIn(BaseModel):
    tax_type: str
    period_id: str
    what_changed: str | None = None


@router.post("")
def create(company_id: str, body: CreateIn, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    _guard_role(principal, company_id)
    bk.require_function(principal, company_id, "tax_preparation")
    try:
        pack = svc.create_pack(db, company_id, body.tax_type, body.period_id, actor=principal, what_changed=body.what_changed)
    except ValidationFailed:
        db.commit()  # keep the completeness check, failure event and any scope escalation
        raise
    db.commit()
    return svc.pack_dict(db, pack, role=bk.role_for(principal, company_id), lang=principal.language)


@router.get("/checklist/{tax_type}/{period_id}")
def checklist(company_id: str, tax_type: str, period_id: str, principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    """Completeness checklist (dc-v1): Item, Why we need it, Who can supply it, Action, status."""
    from app.modules.tax.service import completeness_facts

    _guard_role(principal, company_id)
    check = bk.evaluate_completeness(db, company_id, tax_type, period_id, facts=completeness_facts(db, company_id, tax_type))
    db.commit()
    return {"passed": check.passed, "missing_count": len(check.missing_items), "items": check.missing_items, "version": check.version, "heading": (f"We cannot prepare this draft yet. {len(check.missing_items)} items are missing." if not check.passed else "All items received. We are preparing your draft.")}


@router.get("/{pack_id}")
def get_pack(company_id: str, pack_id: str, principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    role = _guard_role(principal, company_id)
    pack = _pack_for(db, company_id, pack_id)
    if pack.on_hold and role != "owner":
        raise Forbidden("You do not have access to this page.", reason_code="ON_HOLD_OWNER_ONLY")
    svc.check_out_of_date(db, pack)
    record_event(db, event_type="DRAFT_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="draft_pack", subject_id=pack.id)
    db.commit()
    return svc.pack_dict(db, pack, role=role, lang=principal.language) | {"strings": _strings(principal.language), "role": role, "only_owner_can_approve": role != "owner"}


class ReviewIn(BaseModel):
    to_status: str
    reason_code: str | None = None
    reason_text: str | None = None
    changed_fields: list[str] | None = None


@router.post("/{pack_id}/send-for-review")
def send_for_review(company_id: str, pack_id: str, principal: Principal = Depends(require("returns.send_for_approval")), db: Session = Depends(get_db)):
    """Delegate sends the current version to the owner: 'under review' (approval itself is E6-S1)."""
    role = _guard_role(principal, company_id)
    pack = _pack_for(db, company_id, pack_id)
    if pack.review_status == "not_reviewed" and role == "delegate":
        svc.transition(db, pack, "prepared", principal)
    svc.transition(db, pack, "under_review", principal)
    record_event(db, event_type="DRAFT_SENT_FOR_OWNER_REVIEW", category="sign_off", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="draft_pack", subject_id=pack.id)
    db.commit()
    return svc.pack_dict(db, pack, role=role, lang=principal.language)


@router.post("/{pack_id}/record-review")
def record_review(company_id: str, pack_id: str, body: ReviewIn, principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    role = _guard_role(principal, company_id)
    pack = _pack_for(db, company_id, pack_id)
    svc.transition(db, pack, body.to_status, principal, reason_code=body.reason_code, reason_text=body.reason_text, changed_fields=body.changed_fields)
    db.commit()
    return svc.pack_dict(db, pack, role=role, lang=principal.language)


class EditIn(BaseModel):
    key: str
    value_fils: int
    reason_code: str
    reason_text: str | None = None


@router.post("/{pack_id}/edit")
def edit(company_id: str, pack_id: str, body: EditIn, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    role = _guard_role(principal, company_id)
    pack = _pack_for(db, company_id, pack_id)
    svc.edit_figure(db, pack, principal, key=body.key, value_fils=body.value_fils, reason_code=body.reason_code, reason_text=body.reason_text)
    db.commit()
    return svc.pack_dict(db, pack, role=role, lang=principal.language)


@router.get("/{pack_id}/export")
def export(company_id: str, pack_id: str, lang: str = "en", principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    _guard_role(principal, company_id)
    pack = _pack_for(db, company_id, pack_id)
    doc = svc.export_pack(db, pack, principal, lang=lang)
    db.commit()
    return doc


class HoldIn(BaseModel):
    decision: str
    reason_code: str
    reason_text: str | None = None


@router.post("/{pack_id}/hold-decision")
def hold_decision(company_id: str, pack_id: str, body: HoldIn, principal: Principal = Depends(require("bookkeeping.quarantine.decide")), db: Session = Depends(get_db)):
    pack = _pack_for(db, company_id, pack_id)
    out = svc.decide_hold(db, pack, principal, decision=body.decision, reason_code=body.reason_code, reason_text=body.reason_text)
    db.commit()
    return out


@router.get("/reference/rubric")
def rubric(company_id: str, principal: Principal = Depends(require("returns.view")), db: Session = Depends(get_db)):
    from app.modules.config.service import get_config

    return {"rubric": get_config(db, "drafts.reason_rubric", svc.REASON_RUBRIC_DEFAULT), "label": "six options plus free text; options not enumerated in source (to be confirmed)"}
