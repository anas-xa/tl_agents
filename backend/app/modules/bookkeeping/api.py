"""Bookkeeping API (E5-S1): review queue, corrections, undo, quarantine decisions, K14 sampling, K17 timing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_principal, require
from app.core.db import get_db
from app.core.errors import Forbidden
from app.core.time import dubai_today
from app.modules.access.service import STAFF_PERMS, Principal, authorize, require_company_access
from app.modules.audit.service import record_event
from app.modules.bookkeeping import service as svc
from app.modules.bookkeeping.strings import STRINGS

router = APIRouter(prefix="/api/companies/{company_id}", tags=["bookkeeping"])


def _strings(lang: str) -> dict[str, str]:
    return {k: v.get(lang) or v["en"] for k, v in STRINGS.items()}


@router.get("/transactions")
def list_transactions(company_id: str, status: str | None = None, period: str | None = None, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    role = svc.role_for(principal, company_id)
    gate = {"bank": svc.consent_state(db, company_id, "bank"), "ledger": svc.consent_state(db, company_id, "ledger")}
    counts = svc.counts(db, company_id)
    record_event(db, event_type="TRANSACTIONS_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"status": status or "all"})
    base = {"company_id": company_id, "role": role, "consent": gate, "counts": counts, "strings": _strings(principal.language), "ai_label": "AI-prepared, draft. Please check before posting."}
    if role == "delegate" and not svc.has_function(principal, company_id, "bookkeeping"):
        db.commit()
        return base | {"view": "no_function", "rows": [], "message": STRINGS["no_function"][principal.language if principal.language in ("en", "ar") else "en"]}
    if role == "remote_owner":
        db.commit()
        return base | {"view": "summary", "rows": []}
    if role not in ("owner", "delegate"):
        db.commit()
        return base | {"view": "read_only", "rows": svc.list_queue(db, company_id, status=status, period=period, include_quarantined=False)}
    rows = svc.list_queue(db, company_id, status=status, period=period, include_quarantined=(role == "owner"))
    db.commit()
    return base | {"view": "full", "rows": rows, "can_decide_quarantine": role == "owner"}


@router.get("/bookkeeping/reference")
def reference(company_id: str, on: str | None = None, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    from datetime import date

    d = date.fromisoformat(on) if on else dubai_today()
    return {
        "categories": list(svc.CATEGORIES),
        "vat_codes": [{"code": v.code, "name_en": v.name_en, "name_ar": v.name_ar, "gloss_en": v.gloss_en, "gloss_ar": v.gloss_ar, "rate_percent": v.rate_percent, "return_box_ref": v.return_box_ref, "version_id": v.version_id, "status_label": v.status_label, "instrument_ref": v.instrument_ref} for v in svc.vat_codes_effective(db, d)],
        "accounts": [{"code": a.code, "name_en": a.name_en, "name_ar": a.name_ar, "reporting_line": a.reporting_line, "version_id": a.version_id} for a in svc.chart_effective(db, d)],
    }


@router.post("/transactions/classify-all")
def classify_all(company_id: str, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    svc.require_function(principal, company_id, "bookkeeping")
    svc.ingest_from_statement_lines(db, company_id)
    out = svc.classify_pending(db, company_id, actor_key=principal.actor_key)
    db.commit()
    return out


@router.post("/transactions/ingest-demo")
def ingest_demo(company_id: str, principal: Principal = Depends(require("tax.prepare")), db: Session = Depends(get_db)):
    """Demo-only intake (labelled 'Demo data'): loads the fixture statement when no datalinks module exists."""
    from app.modules.bookkeeping.seed import demo_rows_for

    svc.require_function(principal, company_id, "bookkeeping")
    rows = demo_rows_for(company_id)
    created = svc.ingest_transactions(db, company_id, rows, source_kind="manual", source_system="demo_statement", consent_id=None)
    db.commit()
    return {"ingested": len(created), "label": "Demo data"}


class CorrectIn(BaseModel):
    category: str
    vat_code: str
    ledger_account: str | None = None
    counterparty: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class BulkIn(BaseModel):
    ids: list[str] | None = None
    confirm: bool = False


class QuarantineIn(BaseModel):
    decision: str
    reason: str
    ids: list[str] | None = None


@router.post("/transactions/{classification_id}/accept")
def accept(company_id: str, classification_id: str, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    cls = svc.accept(db, company_id, classification_id, principal)
    db.commit()
    return svc.to_row(cls, db.get(svc.Transaction, cls.txn_id))


@router.post("/transactions/{classification_id}/correct")
def correct(company_id: str, classification_id: str, body: CorrectIn, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    cls = svc.correct(db, company_id, classification_id, principal, category=body.category, vat_code=body.vat_code, ledger_account=body.ledger_account, counterparty=body.counterparty)
    db.commit()
    return svc.to_row(cls, db.get(svc.Transaction, cls.txn_id))


@router.post("/transactions/{classification_id}/reject")
def reject(company_id: str, classification_id: str, body: ReasonIn | None = None, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    cls = svc.reject(db, company_id, classification_id, principal, reason=body.reason if body else None)
    db.commit()
    return svc.to_row(cls, db.get(svc.Transaction, cls.txn_id))


@router.post("/transactions/{classification_id}/post")
def retry_post(company_id: str, classification_id: str, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    cls = svc.retry_post(db, company_id, classification_id, principal)
    db.commit()
    return svc.to_row(cls, db.get(svc.Transaction, cls.txn_id))


@router.post("/transactions/{classification_id}/undo")
def undo(company_id: str, classification_id: str, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    cls = svc.undo(db, company_id, classification_id, principal)
    db.commit()
    return svc.to_row(cls, db.get(svc.Transaction, cls.txn_id))


@router.post("/transactions/bulk-accept")
def bulk_accept(company_id: str, body: BulkIn, principal: Principal = Depends(require("tax.correct")), db: Session = Depends(get_db)):
    if not body.confirm:
        out = svc.bulk_accept_preview(db, company_id, body.ids)
        db.commit()
        return out
    out = svc.bulk_accept(db, company_id, principal, body.ids)
    db.commit()
    return out


@router.post("/transactions/quarantine-decision")
def quarantine_decision(company_id: str, body: QuarantineIn, principal: Principal = Depends(require("bookkeeping.quarantine.decide")), db: Session = Depends(get_db)):
    n = svc.decide_quarantine(db, company_id, principal, decision=body.decision, reason=body.reason, classification_ids=body.ids)
    db.commit()
    return {"decided": n, "decision": body.decision}


@router.get("/transactions/timing/{return_type}/{period_id}")
def timing(company_id: str, return_type: str, period_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    return svc.timing_card(db, company_id, return_type, period_id)


@router.post("/transactions/timing/{return_type}/{period_id}/evaluate")
def evaluate(company_id: str, return_type: str, period_id: str, principal: Principal = Depends(require("tax.view")), db: Session = Depends(get_db)):
    facts = None
    try:
        from app.modules.tax.service import completeness_facts

        facts = completeness_facts(db, company_id, return_type)
    except ImportError:  # pragma: no cover
        pass
    check = svc.evaluate_completeness(db, company_id, return_type, period_id, facts=facts)
    db.commit()
    return {"passed": check.passed, "missing_items": check.missing_items, "version": check.version, "card": svc.timing_card(db, company_id, return_type, period_id)}


# --- K14 sampling: company principal with tax.view, or staff with cases.queue.tax ----------------


def _sampling_principal(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
    company_id = request.path_params["company_id"]
    if principal.staff_roles and any("cases.queue.tax" in STAFF_PERMS.get(r, set()) for r in principal.staff_roles):
        db.commit()
        return principal
    require_company_access(db, principal, company_id)
    authorize(db, principal, "tax.view", company_id=company_id)
    db.commit()
    return principal


@router.get("/bookkeeping/samples")
def samples(company_id: str, month: str, principal: Principal = Depends(_sampling_principal), db: Session = Depends(get_db)):
    """K14 rate for the month (labelled correction rate). Sample ids are shown to staff only (blind review)."""
    out = svc.k14_rate(db, company_id, month)
    if not principal.staff_roles:
        for s in out["strata"]:
            s.pop("seed", None)
    record_event(db, event_type="K14_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"month": month})
    db.commit()
    return out


class DrawIn(BaseModel):
    month: str


@router.post("/bookkeeping/samples/draw")
def draw(company_id: str, body: DrawIn, principal: Principal = Depends(_sampling_principal), db: Session = Depends(get_db)):
    if not principal.staff_roles and svc.role_for(principal, company_id) != "owner":
        raise Forbidden("only staff reviewers or the owner draw samples", reason_code="NO_PERMISSION")
    runs = svc.draw_month(db, company_id, body.month, actor_key=principal.actor_key)
    db.commit()
    return [{"id": r.id, "month": r.month, "language_class": r.language_class, "N": r.population_count, "n": r.n, "status": r.status, "rule_version": r.sampling_rule_version, "seed": r.seed, "sample_ids": r.sample_ids if principal.staff_roles else None} for r in runs]
